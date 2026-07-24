import { ROOT_LOGGER, type RootLogger } from "@posthog/di/logger";
import {
  type IPowerManager,
  POWER_MANAGER_SERVICE,
} from "@posthog/platform/power-manager";
import {
  type BackoffOptions,
  type CloudRegion,
  getCloudUrlFromRegion,
  NotAuthenticatedError,
  OAUTH_SCOPE_VERSION,
  sleepWithBackoff,
  TypedEventEmitter,
  withTimeout,
} from "@posthog/shared";
import { inject, injectable, postConstruct, preDestroy } from "inversify";
import {
  AUTH_CONNECTIVITY,
  AUTH_OAUTH_FLOW_SERVICE,
  AUTH_PREFERENCE_STORE,
  AUTH_SESSION_STORE,
  AUTH_TOKEN_CIPHER,
  AUTH_TOKEN_OVERRIDE,
  type IAuthConnectivity,
  type IAuthOAuthFlowService,
  type IAuthPreferenceStore,
  type IAuthSessionStore,
  type IAuthTokenCipher,
} from "./identifiers";
import {
  AuthServiceEvent,
  type AuthServiceEvents,
  type AuthState,
  type AuthTokenResponse,
  findOrgForProject,
  flattenProjectIds,
  type OrgProjects,
  type OrgProjectsMap,
  pickInitialProjectId,
  type ValidAccessTokenOutput,
} from "./schemas";

const TOKEN_EXPIRY_SKEW_MS = 60_000;
const AUTH_FETCH_TIMEOUT_MS = 30_000;
const AUTH_BOOTSTRAP_DEADLINE_MS = 20_000;
type FetchLike = (
  input: string | Request,
  init?: RequestInit,
) => Promise<Response>;

interface InMemorySession {
  accountKey: string | null;
  accessToken: string;
  accessTokenExpiresAt: number;
  refreshToken: string;
  cloudRegion: CloudRegion;
  orgProjectsMap: OrgProjectsMap;
  currentOrgId: string | null;
  currentProjectId: number | null;
  orgProjectsIncomplete: boolean;
}

interface StoredSessionInput {
  refreshToken: string;
  cloudRegion: CloudRegion;
  selectedProjectId: number | null;
}

interface TokenResponseOptions {
  cloudRegion: CloudRegion;
  selectedProjectId: number | null;
}

@injectable()
export class AuthService extends TypedEventEmitter<AuthServiceEvents> {
  private state: AuthState = {
    status: "anonymous",
    bootstrapComplete: false,
    cloudRegion: null,
    orgProjectsMap: {},
    currentOrgId: null,
    currentProjectId: null,
    hasCodeAccess: null,
    needsScopeReauth: false,
  };
  private session: InMemorySession | null = null;
  private initializePromise: Promise<void> | null = null;
  private refreshPromise: Promise<InMemorySession> | null = null;
  // Serializes session-state commits so overlapping selections can't
  // interleave across async encryption (see commitSessionState).
  private commitChain: Promise<void> = Promise.resolve();
  constructor(
    @inject(AUTH_PREFERENCE_STORE)
    private readonly authPreference: IAuthPreferenceStore,
    @inject(AUTH_SESSION_STORE)
    private readonly authSession: IAuthSessionStore,
    @inject(AUTH_OAUTH_FLOW_SERVICE)
    private readonly oauthFlow: IAuthOAuthFlowService,
    @inject(AUTH_CONNECTIVITY)
    private readonly connectivity: IAuthConnectivity,
    @inject(AUTH_TOKEN_CIPHER)
    private readonly cipher: IAuthTokenCipher,
    @inject(POWER_MANAGER_SERVICE)
    private readonly powerManager: IPowerManager,
    @inject(ROOT_LOGGER)
    private readonly logger: RootLogger,
    @inject(AUTH_TOKEN_OVERRIDE)
    private readonly tokenOverride: string | null,
  ) {
    super();
  }
  async initialize(): Promise<void> {
    if (this.initializePromise) {
      return this.initializePromise;
    }

    this.initializePromise = this.doInitialize();
    return this.initializePromise;
  }
  getState(): AuthState {
    return { ...this.state };
  }
  async login(region: CloudRegion): Promise<AuthState> {
    await this.authenticateWithFlow(
      () => this.oauthFlow.startFlow(region),
      region,
      "OAuth flow failed",
    );
    return this.getState();
  }
  async signup(region: CloudRegion): Promise<AuthState> {
    await this.authenticateWithFlow(
      () => this.oauthFlow.startSignupFlow(region),
      region,
      "Signup failed",
    );
    return this.getState();
  }
  async getValidAccessToken(): Promise<ValidAccessTokenOutput> {
    const override = this.tokenOverride;
    if (override) {
      await this.initialize();
      const region = this.session?.cloudRegion ?? "us";
      return {
        accessToken: override,
        apiHost: getCloudUrlFromRegion(region),
      };
    }

    await this.initialize();

    const session = await this.ensureValidSession();
    return {
      accessToken: session.accessToken,
      apiHost: getCloudUrlFromRegion(session.cloudRegion),
    };
  }
  async getOAuthCredentials(): Promise<{
    access: string;
    refresh: string;
    expires: number;
    region: CloudRegion;
  } | null> {
    if (this.tokenOverride) return null;
    await this.initialize();
    const session = await this.ensureValidSession();
    return {
      access: session.accessToken,
      refresh: session.refreshToken,
      expires: session.accessTokenExpiresAt,
      region: session.cloudRegion,
    };
  }
  async refreshAccessToken(): Promise<ValidAccessTokenOutput> {
    const override = this.tokenOverride;
    if (override) {
      await this.initialize();
      const region = this.session?.cloudRegion ?? "us";
      return {
        accessToken: override,
        apiHost: getCloudUrlFromRegion(region),
      };
    }

    await this.initialize();

    const session = await this.ensureValidSession(true);
    return {
      accessToken: session.accessToken,
      apiHost: getCloudUrlFromRegion(session.cloudRegion),
    };
  }
  async invalidateAccessTokenForTest(): Promise<void> {
    await this.initialize();

    if (!this.session) {
      return;
    }

    this.session = {
      ...this.session,
      accessToken: `${this.session.accessToken}_invalid`,
      accessTokenExpiresAt: Date.now() + 5 * 60 * 1000,
    };
  }
  async authenticatedFetch(
    fetchImpl: FetchLike,
    input: string | Request,
    init: RequestInit = {},
  ): Promise<Response> {
    const initialAuth = await this.getValidAccessToken();
    let response = await this.executeAuthenticatedFetch(
      fetchImpl,
      input,
      init,
      initialAuth.accessToken,
    );

    if (response.status === 401 || response.status === 403) {
      const refreshedAuth = await this.refreshAccessToken();
      response = await this.executeAuthenticatedFetch(
        fetchImpl,
        input,
        init,
        refreshedAuth.accessToken,
      );
    }

    return response;
  }
  async redeemInviteCode(code: string): Promise<AuthState> {
    const { apiHost } = await this.getValidAccessToken();
    const response = await this.authenticatedFetch(
      fetch,
      `${apiHost}/api/code/invites/redeem/`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code }),
      },
    );

    const data = (await response.json().catch(() => ({}))) as {
      success?: boolean;
      error?: string;
    };

    if (!response.ok || !data.success) {
      throw new Error(data.error || "Failed to redeem invite code");
    }

    this.updateState({ hasCodeAccess: true });
    return this.getState();
  }
  async selectProject(projectId: number): Promise<AuthState> {
    await this.initialize();

    const session = this.requireSession();

    if (!flattenProjectIds(session.orgProjectsMap).includes(projectId)) {
      throw new Error("Invalid project selection");
    }

    const newOrgId =
      findOrgForProject(
        session.orgProjectsMap,
        projectId,
        session.currentOrgId,
      ) ?? session.currentOrgId;

    const orgProjectsMap =
      newOrgId && newOrgId !== session.currentOrgId
        ? await this.applyOrgChange(session, newOrgId)
        : session.orgProjectsMap;

    await this.commitSessionState(session, {
      orgProjectsMap,
      currentOrgId: newOrgId,
      currentProjectId: projectId,
    });
    return this.getState();
  }
  async switchOrg(orgId: string): Promise<AuthState> {
    await this.initialize();

    const session = this.requireSession();

    if (!session.orgProjectsMap[orgId]) {
      throw new Error("Invalid organization");
    }

    const orgProjectsMap = await this.applyOrgChange(session, orgId);
    const currentProjectId = this.pickProjectForOrg(
      session,
      orgProjectsMap,
      orgId,
    );

    await this.commitSessionState(session, {
      orgProjectsMap,
      currentOrgId: orgId,
      currentProjectId,
    });
    return this.getState();
  }
  private async applyOrgChange(
    session: InMemorySession,
    orgId: string,
  ): Promise<OrgProjectsMap> {
    await this.patchCurrentOrganization(orgId);
    const refreshedProjects = await this.fetchOrgProjects(
      session.accessToken,
      session.cloudRegion,
      orgId,
    );
    if (!refreshedProjects) {
      return session.orgProjectsMap;
    }
    return {
      ...session.orgProjectsMap,
      [orgId]: {
        orgName: session.orgProjectsMap[orgId]?.orgName ?? "(unknown)",
        projects: refreshedProjects,
      },
    };
  }
  private pickProjectForOrg(
    session: InMemorySession,
    orgProjectsMap: OrgProjectsMap,
    orgId: string,
  ): number | null {
    const orgProjects = orgProjectsMap[orgId]?.projects ?? [];
    const preferredProjectId = session.accountKey
      ? (this.authPreference.getOrgProject(
          session.accountKey,
          session.cloudRegion,
          orgId,
        )?.lastSelectedProjectId ?? null)
      : null;
    if (
      preferredProjectId &&
      orgProjects.some((p) => p.id === preferredProjectId)
    ) {
      return preferredProjectId;
    }
    return orgProjects[0]?.id ?? null;
  }
  private commitSessionState(
    prevSession: InMemorySession,
    next: {
      orgProjectsMap: OrgProjectsMap;
      currentOrgId: string | null;
      currentProjectId: number | null;
    },
  ): Promise<void> {
    // Serialize commits onto a chain so overlapping selections can't
    // interleave across async encryption and clobber a newer one. The chain
    // swallows rejections so one failure doesn't wedge later commits; the
    // returned promise still rejects for the caller.
    const run = this.commitChain.then(() =>
      this.applyCommittedSession(prevSession, next),
    );
    this.commitChain = run.catch(() => {});
    return run;
  }
  private async applyCommittedSession(
    prevSession: InMemorySession,
    next: {
      orgProjectsMap: OrgProjectsMap;
      currentOrgId: string | null;
      currentProjectId: number | null;
    },
  ): Promise<void> {
    const nextSession: InMemorySession = {
      ...prevSession,
      orgProjectsMap: next.orgProjectsMap,
      currentOrgId: next.currentOrgId,
      currentProjectId: next.currentProjectId,
      orgProjectsIncomplete: false,
    };

    // Persist the durable session first — the only step that can fail (async
    // encryption may reject). Mutate this.session, the preference, and
    // published state only after it resolves, so a rejection leaves every
    // layer on the prior session.
    await this.persistSession({
      refreshToken: nextSession.refreshToken,
      cloudRegion: nextSession.cloudRegion,
      selectedProjectId: next.currentProjectId,
    });

    this.session = nextSession;
    this.persistProjectPreference(nextSession);
    this.updateState({
      orgProjectsMap: next.orgProjectsMap,
      currentOrgId: next.currentOrgId,
      currentProjectId: next.currentProjectId,
    });
  }
  private async patchCurrentOrganization(orgId: string): Promise<void> {
    const { apiHost } = await this.getValidAccessToken();
    const response = await this.authenticatedFetch(
      fetch,
      `${apiHost}/api/users/@me/`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ set_current_organization: orgId }),
      },
    );

    if (!response.ok) {
      throw new Error(`Failed to switch organization: ${response.statusText}`);
    }
  }
  async logout(): Promise<AuthState> {
    const { cloudRegion, currentProjectId } = this.state;

    this.authSession.clearCurrent();
    this.session = null;
    this.setAnonymousState({ cloudRegion, currentProjectId });
    return this.getState();
  }
  private executeAuthenticatedFetch(
    fetchImpl: FetchLike,
    input: string | Request,
    init: RequestInit,
    accessToken: string,
  ): Promise<Response> {
    const headers = new Headers(init.headers);
    headers.set("authorization", `Bearer ${accessToken}`);

    return fetchImpl(input, {
      ...init,
      headers,
      signal: init.signal ?? AbortSignal.timeout(AUTH_FETCH_TIMEOUT_MS),
    });
  }
  private async doInitialize(): Promise<void> {
    const stored = this.authSession.getCurrent();

    if (!stored) {
      this.setAnonymousState({ bootstrapComplete: true });
      return;
    }

    if (stored.scopeVersion < OAUTH_SCOPE_VERSION) {
      this.session = null;
      this.setAnonymousState({
        bootstrapComplete: true,
        cloudRegion: stored.cloudRegion,
        currentProjectId: stored.selectedProjectId,
        needsScopeReauth: true,
      });
      return;
    }

    const storedSession = await this.resolveStoredSession();
    if (!storedSession) {
      this.logger.warn("Stored auth session could not be decrypted");
      this.authSession.clearCurrent();
      this.setAnonymousState({ bootstrapComplete: true });
      return;
    }

    this.setRestoringState(storedSession, false);

    try {
      const restore = this.ensureValidSession().then(() => undefined);
      const outcome = await withTimeout(restore, AUTH_BOOTSTRAP_DEADLINE_MS);
      if (outcome.result === "timeout") {
        this.logger.warn(
          "Auth bootstrap exceeded deadline; completing bootstrap while the restore continues in the background",
        );
        // A stored session that is merely slow to refresh must not strand the
        // renderer on the boot screen. Complete bootstrap but stay "restoring"
        // so a late success still upgrades and consumers don't treat the delay
        // as a logout.
        this.completeBootstrapWhileRestoring(storedSession);
        restore.catch((error) => {
          this.logger.warn("Background auth restore failed after deadline", {
            error,
          });
          this.handleStoredSessionRestoreFailure(storedSession);
        });
      }
    } catch (error) {
      this.logger.warn("Failed to restore stored auth session", { error });
      this.handleStoredSessionRestoreFailure(storedSession);
    }
  }

  private setRestoringState(
    storedSession: StoredSessionInput,
    bootstrapComplete: boolean,
  ): void {
    this.session = null;
    this.updateState({
      status: "restoring",
      bootstrapComplete,
      cloudRegion: storedSession.cloudRegion,
      orgProjectsMap: {},
      currentOrgId: null,
      currentProjectId: storedSession.selectedProjectId,
      hasCodeAccess: null,
      needsScopeReauth: false,
    });
  }

  private completeBootstrapWhileRestoring(
    storedSession: StoredSessionInput,
  ): void {
    // Only meaningful while the stored session is still on disk: a rejected
    // refresh token clears it and publishes a real anonymous state instead.
    // Transient/offline failures keep the session, so stay "restoring" (no
    // logout side effects) but flip bootstrapComplete so the renderer leaves
    // the boot gate rather than stranding on the loading screen.
    if (this.authSession.getCurrent()) {
      this.setRestoringState(storedSession, true);
    }
  }

  private handleStoredSessionRestoreFailure(
    storedSession: StoredSessionInput,
  ): void {
    this.completeBootstrapWhileRestoring(storedSession);
  }

  private async ensureValidSession(
    forceRefresh = false,
  ): Promise<InMemorySession> {
    const currentSession = this.session;
    if (
      currentSession &&
      !forceRefresh &&
      !this.isSessionExpiring(currentSession)
    ) {
      return currentSession;
    }

    if (this.refreshPromise) {
      return this.refreshPromise;
    }

    // Assign refreshPromise synchronously — no await before this — so
    // concurrent callers dedupe onto one refresh. Resolving the stored session
    // (now async) must happen INSIDE refreshAndSync, else two callers both
    // refresh and burn the rotating token twice.
    const refreshAndSync = async (): Promise<InMemorySession> => {
      const sessionInput = await this.getSessionInputForRefresh();
      let session: InMemorySession;
      try {
        session = await this.refreshSession(sessionInput);
      } catch (error) {
        if (
          currentSession &&
          this.session === currentSession &&
          !forceRefresh &&
          !this.isSessionExpired(currentSession)
        ) {
          this.logger.warn(
            "Preemptive session refresh failed; using current access token",
            { error },
          );
          return currentSession;
        }
        throw error;
      }
      await this.syncAuthenticatedSession(session);
      return session;
    };

    this.refreshPromise = refreshAndSync().finally(() => {
      this.refreshPromise = null;
    });

    return this.refreshPromise;
  }

  private async getSessionInputForRefresh(): Promise<StoredSessionInput> {
    if (this.session) {
      return {
        refreshToken: this.session.refreshToken,
        cloudRegion: this.session.cloudRegion,
        selectedProjectId: this.session.currentProjectId,
      };
    }

    const storedSession = await this.resolveStoredSession();
    if (!storedSession) {
      throw new NotAuthenticatedError();
    }

    return storedSession;
  }
  private async refreshSession(
    input: StoredSessionInput,
  ): Promise<InMemorySession> {
    if (!this.connectivity.getStatus().isOnline) {
      throw new Error("Offline");
    }

    let lastError = "Token refresh failed";

    for (
      let attempt = 0;
      attempt < AuthService.REFRESH_MAX_ATTEMPTS;
      attempt++
    ) {
      const result = await this.oauthFlow.refreshToken(
        input.refreshToken,
        input.cloudRegion,
      );

      if (result.success && result.data) {
        return await this.createSessionFromTokenResponse(result.data, input);
      }

      lastError = result.error || "Token refresh failed";

      if (result.errorCode === "auth_error") {
        this.logger.warn("Refresh token rejected by server, forcing logout");
        this.authSession.clearCurrent();
        this.session = null;
        this.setAnonymousState({
          cloudRegion: input.cloudRegion,
          currentProjectId: input.selectedProjectId,
        });
        throw new Error(lastError);
      }

      const isRetryable =
        result.errorCode === "network_error" ||
        result.errorCode === "server_error";

      if (!isRetryable) {
        throw new Error(lastError);
      }

      const isLastAttempt = attempt === AuthService.REFRESH_MAX_ATTEMPTS - 1;
      if (isLastAttempt) break;

      this.logger.warn("Transient refresh failure, retrying", {
        attempt,
        errorCode: result.errorCode,
      });
      await sleepWithBackoff(attempt, AuthService.REFRESH_BACKOFF);
    }

    throw new Error(lastError);
  }
  private async createSessionFromTokenResponse(
    tokenResponse: AuthTokenResponse,
    options: TokenResponseOptions,
  ): Promise<InMemorySession> {
    const scopedOrgIds = tokenResponse.scoped_organizations ?? [];
    const { accountKey, currentOrgId } = await this.fetchUserContext(
      tokenResponse.access_token,
      options.cloudRegion,
    );
    // Team-scoped tokens (required_access_level=project) can arrive with an
    // empty scoped_organizations list — the server only populates scoped_teams.
    // Fall back to the current org from /api/users/@me/ so the picker isn't
    // empty; without this the user is stranded on "No projects".
    const orgIdsToFetch =
      scopedOrgIds.length > 0
        ? scopedOrgIds
        : currentOrgId
          ? [currentOrgId]
          : [];
    const { map: orgProjectsMap, incomplete: orgProjectsIncomplete } =
      await this.buildOrgProjectsMap(
        tokenResponse.access_token,
        options.cloudRegion,
        orgIdsToFetch,
        this.session?.orgProjectsMap ?? {},
      );
    const lastPrefs = accountKey
      ? this.authPreference.get(accountKey, options.cloudRegion)
      : null;
    const currentProjectId = pickInitialProjectId({
      orgProjectsMap,
      currentOrgId,
      preferredProjectId:
        options.selectedProjectId ?? lastPrefs?.lastSelectedProjectId ?? null,
      lastSelectedOrgId: lastPrefs?.lastSelectedOrgId ?? null,
    });

    const session: InMemorySession = {
      accountKey,
      accessToken: tokenResponse.access_token,
      accessTokenExpiresAt: Date.now() + tokenResponse.expires_in * 1000,
      refreshToken: tokenResponse.refresh_token,
      cloudRegion: options.cloudRegion,
      orgProjectsMap,
      currentOrgId,
      currentProjectId,
      orgProjectsIncomplete,
    };

    return session;
  }
  private async buildOrgProjectsMap(
    accessToken: string,
    cloudRegion: CloudRegion,
    orgIds: string[],
    previousMap: OrgProjectsMap,
  ): Promise<{ map: OrgProjectsMap; incomplete: boolean }> {
    let incomplete = false;
    const entries = await Promise.all(
      orgIds.map(async (orgId): Promise<[string, OrgProjects]> => {
        const { org, transient } = await this.fetchOrgWithProjects(
          accessToken,
          cloudRegion,
          orgId,
        );
        if (org) {
          return [orgId, org];
        }
        const fallback = previousMap[orgId] ?? {
          orgName: "(unknown)",
          projects: [],
        };
        if (transient && fallback.projects.length === 0) {
          incomplete = true;
        }
        return [orgId, fallback];
      }),
    );

    return { map: Object.fromEntries(entries), incomplete };
  }
  private async fetchOrgProjects(
    accessToken: string,
    cloudRegion: CloudRegion,
    orgId: string,
  ): Promise<{ id: number; name: string }[] | null> {
    const { org } = await this.fetchOrgWithProjects(
      accessToken,
      cloudRegion,
      orgId,
    );
    return org?.projects ?? null;
  }
  private async fetchOrgWithProjects(
    accessToken: string,
    cloudRegion: CloudRegion,
    orgId: string,
  ): Promise<{ org: OrgProjects | null; transient: boolean }> {
    for (
      let attempt = 0;
      attempt < AuthService.ORG_FETCH_MAX_ATTEMPTS;
      attempt++
    ) {
      const result = await this.fetchOrgWithProjectsOnce(
        accessToken,
        cloudRegion,
        orgId,
      );
      if (result.ok) {
        return { org: result.data, transient: false };
      }
      if (!result.retryable) {
        return { org: null, transient: false };
      }

      const isLastAttempt = attempt === AuthService.ORG_FETCH_MAX_ATTEMPTS - 1;
      if (isLastAttempt) {
        break;
      }

      this.logger.warn("Transient org fetch failure, retrying", {
        orgId,
        attempt,
      });
      await sleepWithBackoff(attempt, AuthService.REFRESH_BACKOFF);
    }

    return { org: null, transient: true };
  }
  private async fetchOrgWithProjectsOnce(
    accessToken: string,
    cloudRegion: CloudRegion,
    orgId: string,
  ): Promise<
    { ok: true; data: OrgProjects } | { ok: false; retryable: boolean }
  > {
    const apiHost = getCloudUrlFromRegion(cloudRegion);
    try {
      const res = await this.executeAuthenticatedFetch(
        fetch,
        `${apiHost}/api/organizations/${orgId}/`,
        {},
        accessToken,
      );
      if (!res.ok) {
        return { ok: false, retryable: res.status >= 500 };
      }
      const raw = (await res.json().catch(() => null)) as {
        name?: unknown;
        teams?: unknown;
      } | null;
      const orgName =
        typeof raw?.name === "string" && raw.name.length > 0
          ? raw.name
          : "(unknown)";
      const teams = Array.isArray(raw?.teams) ? raw.teams : [];
      const projects = teams
        .map((t) => t as { id?: unknown; name?: unknown })
        .filter((t) => typeof t.id === "number" && typeof t.name === "string")
        .map((t) => ({ id: t.id as number, name: t.name as string }));
      return { ok: true, data: { orgName, projects } };
    } catch (error) {
      this.logger.warn("Failed to fetch org with projects", { orgId, error });
      return { ok: false, retryable: true };
    }
  }
  private async authenticateWithFlow(
    runFlow: () => Promise<{
      success: boolean;
      data?: AuthTokenResponse;
      error?: string;
    }>,
    region: CloudRegion,
    fallbackError: string,
  ): Promise<void> {
    const result = await runFlow();
    if (!result.success || !result.data) {
      throw new Error(result.error || fallbackError);
    }

    const session = await this.createSessionFromTokenResponse(result.data, {
      cloudRegion: region,
      selectedProjectId: this.state.currentProjectId,
    });
    await this.syncAuthenticatedSession(session);
  }
  private async syncAuthenticatedSession(
    session: InMemorySession,
  ): Promise<void> {
    this.persistProjectPreference(session);
    await this.persistSession({
      refreshToken: session.refreshToken,
      cloudRegion: session.cloudRegion,
      selectedProjectId: session.currentProjectId,
    });

    this.session = session;
    this.updateState({
      status: "authenticated",
      bootstrapComplete: true,
      cloudRegion: session.cloudRegion,
      orgProjectsMap: session.orgProjectsMap,
      currentOrgId: session.currentOrgId,
      currentProjectId: session.currentProjectId,
      needsScopeReauth: false,
    });
    await this.updateCodeAccessFromSession();

    if (session.orgProjectsIncomplete) {
      void this.refreshOrgProjects();
    }
  }
  private async persistSession(input: {
    refreshToken: string;
    cloudRegion: CloudRegion;
    selectedProjectId: number | null;
  }): Promise<void> {
    const priorSelected =
      this.authSession.getCurrent()?.selectedProjectId ?? null;
    this.authSession.saveCurrent({
      refreshTokenEncrypted: await this.cipher.encrypt(input.refreshToken),
      cloudRegion: input.cloudRegion,
      selectedProjectId: input.selectedProjectId ?? priorSelected,
      scopeVersion: OAUTH_SCOPE_VERSION,
    });
  }
  private persistProjectPreference(session: InMemorySession): void {
    if (!session.accountKey || session.currentProjectId === null) {
      return;
    }

    this.authPreference.save({
      accountKey: session.accountKey,
      cloudRegion: session.cloudRegion,
      lastSelectedProjectId: session.currentProjectId,
      lastSelectedOrgId: session.currentOrgId,
    });

    const orgIdForProject = session.currentProjectId
      ? findOrgForProject(
          session.orgProjectsMap,
          session.currentProjectId,
          session.currentOrgId,
        )
      : null;
    if (orgIdForProject && session.currentProjectId) {
      this.authPreference.saveOrgProject({
        accountKey: session.accountKey,
        cloudRegion: session.cloudRegion,
        orgId: orgIdForProject,
        lastSelectedProjectId: session.currentProjectId,
      });
    }
  }
  private isSessionExpiring(session: InMemorySession): boolean {
    return session.accessTokenExpiresAt - Date.now() <= TOKEN_EXPIRY_SKEW_MS;
  }
  private isSessionExpired(session: InMemorySession): boolean {
    return session.accessTokenExpiresAt <= Date.now();
  }
  private async fetchUserContext(
    accessToken: string,
    cloudRegion: CloudRegion,
  ): Promise<{ accountKey: string | null; currentOrgId: string | null }> {
    try {
      const response = await this.executeAuthenticatedFetch(
        fetch,
        `${getCloudUrlFromRegion(cloudRegion)}/api/users/@me/`,
        {},
        accessToken,
      );

      if (!response.ok) {
        return { accountKey: null, currentOrgId: null };
      }

      const data = (await response.json().catch(() => ({}))) as {
        uuid?: unknown;
        distinct_id?: unknown;
        email?: unknown;
        organization?: { id?: unknown } | null;
      };

      let accountKey: string | null = null;
      if (typeof data.uuid === "string" && data.uuid.length > 0) {
        accountKey = data.uuid;
      } else if (
        typeof data.distinct_id === "string" &&
        data.distinct_id.length > 0
      ) {
        accountKey = data.distinct_id;
      } else if (typeof data.email === "string" && data.email.length > 0) {
        accountKey = data.email;
      }

      const orgId = data.organization?.id;
      const currentOrgId =
        typeof orgId === "string" && orgId.length > 0 ? orgId : null;

      return { accountKey, currentOrgId };
    } catch (error) {
      this.logger.warn("Failed to resolve user context", { error });
      return { accountKey: null, currentOrgId: null };
    }
  }
  private requireSession(): InMemorySession {
    if (!this.session) {
      throw new NotAuthenticatedError();
    }
    return this.session;
  }
  private setAnonymousState(
    partial: Pick<
      Partial<AuthState>,
      | "bootstrapComplete"
      | "cloudRegion"
      | "currentProjectId"
      | "needsScopeReauth"
    > = {},
  ): void {
    this.updateState({
      status: "anonymous",
      bootstrapComplete: partial.bootstrapComplete ?? true,
      cloudRegion: partial.cloudRegion ?? null,
      orgProjectsMap: {},
      currentOrgId: null,
      currentProjectId: partial.currentProjectId ?? null,
      hasCodeAccess: null,
      needsScopeReauth: partial.needsScopeReauth ?? false,
    });
  }
  private async updateCodeAccessFromSession(): Promise<void> {
    if (!this.session) {
      this.updateState({ hasCodeAccess: null });
      return;
    }

    const hasAccess = await this.checkCodeAccess(this.session);

    if (hasAccess !== null) {
      this.updateState({ hasCodeAccess: hasAccess });
      return;
    }

    // Indeterminate: a transient/unauthorized failure isn't proof the invite
    // was revoked, so keep the prior value and let the next sync re-check.
    this.logger.warn(
      "Code access check was inconclusive; keeping previous value",
      { hasCodeAccess: this.state.hasCodeAccess },
    );
  }

  /**
   * Resolves Code invite access. Only a 2xx response with an explicit boolean
   * `has_access` is authoritative; everything else (offline, network error,
   * non-2xx, malformed body) is indeterminate, retried with backoff, then
   * returned as `null` so the caller keeps the prior value. Uses the synced
   * token directly rather than `authenticatedFetch`, which would re-enter the
   * refresh flow this runs inside and deadlock.
   */
  private async checkCodeAccess(
    session: InMemorySession,
  ): Promise<boolean | null> {
    const url = `${getCloudUrlFromRegion(session.cloudRegion)}/api/code/invites/check-access/`;

    for (
      let attempt = 0;
      attempt < AuthService.CODE_ACCESS_MAX_ATTEMPTS;
      attempt++
    ) {
      if (!this.connectivity.getStatus().isOnline) {
        return null;
      }

      try {
        const response = await this.executeAuthenticatedFetch(
          fetch,
          url,
          {},
          session.accessToken,
        );

        if (response.ok) {
          const data = (await response.json().catch(() => null)) as {
            has_access?: unknown;
          } | null;
          if (data && typeof data.has_access === "boolean") {
            return data.has_access;
          }
          this.logger.warn("Code access response missing has_access flag", {
            status: response.status,
          });
        } else {
          this.logger.warn("Code access check returned non-OK status", {
            status: response.status,
          });
        }
      } catch (error) {
        this.logger.warn("Code access check request failed", {
          error,
          attempt,
        });
      }

      const isLastAttempt =
        attempt === AuthService.CODE_ACCESS_MAX_ATTEMPTS - 1;
      if (isLastAttempt) break;
      await sleepWithBackoff(attempt, AuthService.REFRESH_BACKOFF);
    }

    return null;
  }
  private static readonly REFRESH_MAX_ATTEMPTS = 3;
  private static readonly ORG_FETCH_MAX_ATTEMPTS = 3;
  private static readonly CODE_ACCESS_MAX_ATTEMPTS = 3;
  private static readonly ORG_RECOVERY_MAX_ATTEMPTS = 5;
  private static readonly REFRESH_BACKOFF: BackoffOptions = {
    initialDelayMs: 1_000,
    maxDelayMs: 5_000,
    multiplier: 2,
  };
  private recoveryPromise: Promise<void> | null = null;
  private orgProjectsRefreshPromise: Promise<void> | null = null;
  private connectivityUnsubscribe: (() => void) | null = null;
  private resumeUnsubscribe: (() => void) | null = null;
  @postConstruct()
  init(): void {
    this.connectivityUnsubscribe = this.connectivity.onStatusChange(
      (status) => {
        if (status.isOnline) {
          this.attemptSessionRecovery();
        }
      },
    );

    this.resumeUnsubscribe = this.powerManager.onResume(this.handleResume);
  }
  @preDestroy()
  shutdown(): void {
    this.connectivityUnsubscribe?.();
    this.connectivityUnsubscribe = null;
    this.resumeUnsubscribe?.();
    this.resumeUnsubscribe = null;
  }
  private handleResume = (): void => {
    this.attemptSessionRecovery();
  };
  private async resolveStoredSession(): Promise<StoredSessionInput | null> {
    const stored = this.authSession.getCurrent();
    if (!stored) return null;

    const refreshToken = await this.cipher.decrypt(
      stored.refreshTokenEncrypted,
    );
    if (!refreshToken) return null;

    return {
      refreshToken,
      cloudRegion: stored.cloudRegion,
      selectedProjectId: stored.selectedProjectId,
    };
  }
  private attemptSessionRecovery(): void {
    if (this.session) {
      if (this.session.orgProjectsIncomplete) {
        void this.refreshOrgProjects();
      }
      return;
    }
    if (this.recoveryPromise) return;

    const stored = this.authSession.getCurrent();
    if (!stored) return;
    if (stored.scopeVersion < OAUTH_SCOPE_VERSION) return;

    // Claim the recovery slot synchronously so concurrent triggers don't both
    // kick a token refresh; decryptability is now async (Web Crypto), so it's
    // validated inside recoverSession.
    this.recoveryPromise = this.recoverSession()
      .catch((error) => {
        this.logger.warn("Session recovery failed", { error });
      })
      .finally(() => {
        this.recoveryPromise = null;
      });
  }
  private async recoverSession(): Promise<void> {
    // Bail before touching the network if the stored token can't be decrypted.
    if (!(await this.resolveStoredSession())) return;

    // Route through ensureValidSession so a refresh already in flight (e.g. the
    // background bootstrap restore past its deadline) is shared instead of
    // kicking a second concurrent token refresh that would burn the same
    // rotating refresh token twice.
    await this.ensureValidSession();
  }

  private refreshOrgProjects(): Promise<void> {
    if (this.orgProjectsRefreshPromise) {
      return this.orgProjectsRefreshPromise;
    }

    this.orgProjectsRefreshPromise = this.doRefreshOrgProjects()
      .catch((error) => {
        this.logger.warn("Org/projects recovery failed", { error });
      })
      .finally(() => {
        this.orgProjectsRefreshPromise = null;
      });
    return this.orgProjectsRefreshPromise;
  }

  private async doRefreshOrgProjects(): Promise<void> {
    for (
      let attempt = 0;
      attempt < AuthService.ORG_RECOVERY_MAX_ATTEMPTS;
      attempt++
    ) {
      if (!this.session?.orgProjectsIncomplete) return;
      if (!this.connectivity.getStatus().isOnline) return;

      let session: InMemorySession;
      try {
        session = await this.ensureValidSession();
      } catch (error) {
        this.logger.warn("Org/projects recovery aborted: session invalid", {
          error,
        });
        return;
      }

      if (!session.orgProjectsIncomplete) return;

      const orgIds = Object.keys(session.orgProjectsMap);
      const { map, incomplete } = await this.buildOrgProjectsMap(
        session.accessToken,
        session.cloudRegion,
        orgIds,
        session.orgProjectsMap,
      );

      // The session may have been replaced (logout, re-login) while the fetch
      // was in flight; committing the stale one would resurrect it.
      if (this.session !== session) return;

      if (!incomplete) {
        const lastPrefs = session.accountKey
          ? this.authPreference.get(session.accountKey, session.cloudRegion)
          : null;
        const storedSelected =
          this.authSession.getCurrent()?.selectedProjectId ?? null;
        const currentProjectId = pickInitialProjectId({
          orgProjectsMap: map,
          currentOrgId: session.currentOrgId,
          preferredProjectId:
            session.currentProjectId ??
            storedSelected ??
            lastPrefs?.lastSelectedProjectId ??
            null,
          lastSelectedOrgId: lastPrefs?.lastSelectedOrgId ?? null,
        });
        await this.commitSessionState(session, {
          orgProjectsMap: map,
          currentOrgId: session.currentOrgId,
          currentProjectId,
        });
        this.logger.info(
          "Recovered organizations/projects after incomplete sync",
        );
        return;
      }

      const isLastAttempt =
        attempt === AuthService.ORG_RECOVERY_MAX_ATTEMPTS - 1;
      if (isLastAttempt) break;

      await sleepWithBackoff(attempt, AuthService.REFRESH_BACKOFF);
    }

    this.logger.warn("Org/projects recovery exhausted retries");
  }

  private updateState(partial: Partial<AuthState>): void {
    this.state = {
      ...this.state,
      ...partial,
    };
    this.emit(AuthServiceEvent.StateChanged, this.getState());
  }
}
