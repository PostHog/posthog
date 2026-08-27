import { isAuthFailureResponse } from "@posthog/api-client/fetcher";
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
  type DesktopAccess,
  desktopAccessResponseSchema,
  findOrgForProject,
  flattenProjectIds,
  type OrgProjects,
  type OrgProjectsMap,
  pickInitialProjectId,
  type ValidAccessTokenOutput,
} from "./schemas";

// A refresh failure that is not a rejection is no evidence the token is dead, so
// pause rather than retire. Sized inside TOKEN_EXPIRY_SKEW_MS so a fast failure
// still retries on a live token. Retry exhaustion can already outrun the skew on
// its own, so the sizing buys nothing there.
const FAILED_REFRESH_COOLDOWN_MS = 15_000;
const TOKEN_EXPIRY_SKEW_MS = 60_000;
const AUTH_FETCH_TIMEOUT_MS = 30_000;
const AUTH_BOOTSTRAP_DEADLINE_MS = 20_000;
export type FetchLike = (
  input: string | Request,
  init?: RequestInit,
) => Promise<Response>;

interface InMemorySession {
  accountKey: string | null;
  accessToken: string;
  accessTokenExpiresAt: number;
  refreshToken: string | null;
  sessionType: "persistent" | "impersonated";
  cloudRegion: CloudRegion;
  orgProjectsMap: OrgProjectsMap;
  currentOrgId: string | null;
  currentProjectId: number | null;
  orgProjectsIncomplete: boolean;
  scopedTeamIds: number[];
}

interface StoredSessionInput {
  refreshToken: string;
  cloudRegion: CloudRegion;
  selectedProjectId: number | null;
}

interface TokenResponseOptions {
  cloudRegion: CloudRegion;
  selectedProjectId: number | null;
  fallbackRefreshToken?: string;
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
    desktopAccess: { projectId: null, status: "unchecked", reason: null },
    needsScopeReauth: false,
    sessionType: null,
    sessionExpiresAt: null,
    sessionEndReason: null,
  };
  private session: InMemorySession | null = null;
  private initializePromise: Promise<void> | null = null;
  private refreshPromise: Promise<InMemorySession> | null = null;
  private impersonationExpiryTimer: ReturnType<typeof setTimeout> | null = null;
  private sessionGeneration = 0;
  // A refresh already refused, keyed to the session generation so every teardown
  // invalidates it. `until: null` is a proven-dead token, a timestamp is a pause.
  private refusedRefresh: {
    token: string;
    generation: number;
    until: number | null;
  } | null = null;
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
    this.sessionGeneration += 1;
    const sessionGeneration = this.sessionGeneration;
    await this.authenticateWithFlow(
      () => this.oauthFlow.startFlow(region),
      region,
      "OAuth flow failed",
      sessionGeneration,
    );
    return this.getState();
  }
  async signup(region: CloudRegion): Promise<AuthState> {
    this.sessionGeneration += 1;
    const sessionGeneration = this.sessionGeneration;
    await this.authenticateWithFlow(
      () => this.oauthFlow.startSignupFlow(region),
      region,
      "Signup failed",
      sessionGeneration,
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
    refresh: string | null;
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

    if (
      response.status === 403 &&
      this.session?.sessionType === "impersonated"
    ) {
      return response;
    }

    if (await isAuthFailureResponse(response)) {
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

    return this.retryDesktopAccess();
  }
  async retryDesktopAccess(): Promise<AuthState> {
    await this.initialize();
    const session = await this.ensureValidSession();
    this.updateState({
      desktopAccess: {
        projectId: session.currentProjectId,
        status: "checking",
        reason: null,
      },
    });
    await this.updateDesktopAccessFromSession(session);
    return this.getState();
  }
  async selectProject(projectId: number): Promise<AuthState> {
    await this.initialize();

    const session = await this.ensureValidSession();

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

    const session = await this.ensureValidSession();

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
    const sessionGeneration = this.sessionGeneration;
    const run = this.commitChain.then(() =>
      this.applyCommittedSession(prevSession, next, sessionGeneration),
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
    sessionGeneration: number,
  ): Promise<void> {
    if (this.sessionGeneration !== sessionGeneration) {
      return;
    }

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
    if (nextSession.refreshToken) {
      const persisted = await this.persistSession(
        {
          refreshToken: nextSession.refreshToken,
          cloudRegion: nextSession.cloudRegion,
          selectedProjectId: next.currentProjectId,
        },
        () => this.sessionGeneration === sessionGeneration,
      );
      if (!persisted) {
        return;
      }
    }

    if (this.sessionGeneration !== sessionGeneration) {
      return;
    }
    const desktopAccess = this.carryDesktopAccessInto(nextSession);
    this.session = nextSession;
    this.persistProjectPreference(nextSession);
    this.updateState({
      orgProjectsMap: next.orgProjectsMap,
      currentOrgId: next.currentOrgId,
      currentProjectId: next.currentProjectId,
      desktopAccess,
    });
    await this.updateDesktopAccessFromSession(nextSession);
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
  private reconcileInitialSelection(input: {
    orgProjectsMap: OrgProjectsMap;
    currentOrgId: string | null;
    preferredProjectId: number | null;
    lastSelectedOrgId: string | null;
  }): {
    currentOrgId: string | null;
    currentProjectId: number | null;
  } {
    const currentProjectId = pickInitialProjectId(input);
    const projectOrgId = currentProjectId
      ? findOrgForProject(
          input.orgProjectsMap,
          currentProjectId,
          input.currentOrgId,
        )
      : null;
    const currentOrgId = projectOrgId ?? input.currentOrgId;

    return { currentOrgId, currentProjectId };
  }
  async logout(): Promise<AuthState> {
    const { cloudRegion, currentProjectId } = this.state;

    this.sessionGeneration += 1;
    this.authSession.clearCurrent();
    this.clearImpersonationExpiryTimer();
    this.session = null;
    this.refusedRefresh = null;
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
      desktopAccess: {
        projectId: storedSession.selectedProjectId,
        status: "unchecked",
        reason: null,
      },
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

    if (currentSession && !currentSession.refreshToken) {
      if (!forceRefresh && !this.isSessionExpired(currentSession)) {
        return currentSession;
      }
      this.endImpersonatedSession(currentSession);
      throw new NotAuthenticatedError(
        "Your impersonated session has expired. Impersonate the user again to continue.",
      );
    }

    if (this.refreshPromise) {
      return this.refreshPromise;
    }

    // Assign refreshPromise synchronously — no await before this — so
    // concurrent callers dedupe onto one refresh. Resolving the stored session
    // (now async) must happen INSIDE refreshAndSync, else two callers both
    // refresh and burn the rotating token twice.
    const sessionGeneration = this.sessionGeneration;
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
      const synchronized = await this.syncAuthenticatedSession(
        session,
        sessionGeneration,
      );
      if (!synchronized) {
        throw new NotAuthenticatedError();
      }
      return session;
    };

    this.refreshPromise = refreshAndSync().finally(() => {
      this.refreshPromise = null;
    });

    return this.refreshPromise;
  }

  private async getSessionInputForRefresh(): Promise<StoredSessionInput> {
    if (this.session) {
      if (!this.session.refreshToken) {
        throw new NotAuthenticatedError(
          "Your impersonated session has expired. Impersonate the user again to continue.",
        );
      }
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
  private pauseRefresh(token: string, errorCode: string | undefined): void {
    this.refusedRefresh = {
      token,
      generation: this.sessionGeneration,
      until: Date.now() + FAILED_REFRESH_COOLDOWN_MS,
    };
    this.logger.warn("Refresh failed, pausing this token", { errorCode });
  }

  private async refreshSession(
    input: StoredSessionInput,
  ): Promise<InMemorySession> {
    if (!this.connectivity.getStatus().isOnline) {
      throw new Error("Offline");
    }

    const refused = this.refusedRefresh;
    if (
      refused &&
      refused.token === input.refreshToken &&
      refused.generation === this.sessionGeneration
    ) {
      if (refused.until === null) {
        throw new NotAuthenticatedError(
          "Your session has expired. Sign in again to continue.",
        );
      }
      if (Date.now() < refused.until) {
        throw new Error("Token refresh paused after an unclassified failure");
      }
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
        return await this.createSessionFromTokenResponse(result.data, {
          ...input,
          fallbackRefreshToken: input.refreshToken,
        });
      }

      lastError = result.error || "Token refresh failed";

      if (result.errorCode === "auth_error") {
        this.logger.warn("Refresh token rejected by server, forcing logout");
        this.sessionGeneration += 1;
        this.authSession.clearCurrent();
        this.session = null;
        this.setAnonymousState({
          cloudRegion: input.cloudRegion,
          currentProjectId: input.selectedProjectId,
        });
        // Last, so a throwing teardown leaves no refusal over a live-looking session.
        this.refusedRefresh = {
          token: input.refreshToken,
          generation: this.sessionGeneration,
          until: null,
        };
        // The session is already anonymous, so callers that stop on a dead
        // session must see that class here rather than a trigger later.
        throw new NotAuthenticatedError(lastError);
      }

      const isRetryable =
        result.errorCode === "network_error" ||
        result.errorCode === "server_error";

      if (!isRetryable) {
        // This arm keeps the session and the stored token, so only the pause
        // stops the caller re-presenting it on the next trigger.
        this.pauseRefresh(input.refreshToken, result.errorCode);
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

    // A 5xx endpoint or a captive portal exhausts the budget here, not in the arm
    // above; unpaused, each later trigger spends the whole budget again.
    this.pauseRefresh(input.refreshToken, "retries_exhausted");

    throw new Error(lastError);
  }
  private async createSessionFromTokenResponse(
    tokenResponse: AuthTokenResponse,
    options: TokenResponseOptions,
  ): Promise<InMemorySession> {
    const scopedOrgIds = tokenResponse.scoped_organizations ?? [];
    const scopedTeamIds = tokenResponse.scoped_teams ?? [];
    const {
      accountKey,
      currentOrgId: userOrgId,
      orgNames,
    } = await this.fetchUserContext(
      tokenResponse.access_token,
      options.cloudRegion,
    );

    let currentOrgId = userOrgId;
    let orgProjectsMap: OrgProjectsMap;
    let orgProjectsIncomplete: boolean;
    if (scopedTeamIds.length > 0) {
      // Team-scoped tokens (required_access_level=project) are rejected by the
      // server on every endpoint that isn't project-nested — including
      // /api/organizations/*. Build the map from the scoped projects
      // themselves; going through the org would 403 and strand the user on
      // "No projects".
      ({ map: orgProjectsMap, incomplete: orgProjectsIncomplete } =
        await this.buildScopedTeamProjectsMap(
          tokenResponse.access_token,
          options.cloudRegion,
          scopedTeamIds,
          orgNames,
        ));
      if (!currentOrgId || !orgProjectsMap[currentOrgId]) {
        currentOrgId = Object.keys(orgProjectsMap)[0] ?? currentOrgId;
      }
    } else {
      // Org-scoped tokens can arrive with an empty scoped_organizations list.
      // Fall back to the current org from /api/users/@me/ so the picker isn't
      // empty.
      const orgIdsToFetch =
        scopedOrgIds.length > 0
          ? scopedOrgIds
          : currentOrgId
            ? [currentOrgId]
            : [];
      ({ map: orgProjectsMap, incomplete: orgProjectsIncomplete } =
        await this.buildOrgProjectsMap(
          tokenResponse.access_token,
          options.cloudRegion,
          orgIdsToFetch,
          this.session?.orgProjectsMap ?? {},
        ));
    }
    const lastPrefs = accountKey
      ? this.authPreference.get(accountKey, options.cloudRegion)
      : null;
    const preferredProjectId =
      options.selectedProjectId ?? lastPrefs?.lastSelectedProjectId ?? null;
    const selection = this.reconcileInitialSelection({
      orgProjectsMap,
      currentOrgId,
      preferredProjectId,
      lastSelectedOrgId: lastPrefs?.lastSelectedOrgId ?? null,
    });
    if (
      orgProjectsIncomplete &&
      preferredProjectId !== null &&
      !flattenProjectIds(orgProjectsMap).includes(preferredProjectId)
    ) {
      selection.currentProjectId = null;
    }

    const refreshToken =
      tokenResponse.refresh_token ?? options.fallbackRefreshToken ?? null;
    const session: InMemorySession = {
      accountKey,
      accessToken: tokenResponse.access_token,
      accessTokenExpiresAt: Date.now() + tokenResponse.expires_in * 1000,
      refreshToken,
      sessionType: refreshToken ? "persistent" : "impersonated",
      cloudRegion: options.cloudRegion,
      orgProjectsMap,
      currentOrgId: selection.currentOrgId,
      currentProjectId: selection.currentProjectId,
      orgProjectsIncomplete,
      scopedTeamIds,
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
  private async buildScopedTeamProjectsMap(
    accessToken: string,
    cloudRegion: CloudRegion,
    teamIds: number[],
    orgNames: Record<string, string>,
  ): Promise<{ map: OrgProjectsMap; incomplete: boolean }> {
    const apiHost = getCloudUrlFromRegion(cloudRegion);
    let incomplete = false;
    const results = await Promise.all(
      teamIds.map(async (teamId) => {
        try {
          const res = await this.executeAuthenticatedFetch(
            fetch,
            `${apiHost}/api/projects/${teamId}/`,
            {},
            accessToken,
          );
          if (!res.ok) {
            // 4xx means the scoped project is gone or inaccessible — omit it
            // rather than retrying forever through the recovery loop.
            if (res.status >= 500) incomplete = true;
            return null;
          }
          const raw = (await res.json().catch(() => null)) as {
            id?: unknown;
            name?: unknown;
            organization?: unknown;
          } | null;
          if (typeof raw?.id !== "number") return null;
          return {
            orgId:
              typeof raw.organization === "string" &&
              raw.organization.length > 0
                ? raw.organization
                : "(unknown)",
            project: {
              id: raw.id,
              name:
                typeof raw.name === "string" && raw.name.length > 0
                  ? raw.name
                  : `Project ${raw.id}`,
            },
          };
        } catch (error) {
          this.logger.warn("Failed to fetch scoped project", { teamId, error });
          incomplete = true;
          return null;
        }
      }),
    );

    const map: OrgProjectsMap = {};
    for (const result of results) {
      if (!result) continue;
      map[result.orgId] ??= {
        orgName: orgNames[result.orgId] ?? "(unknown)",
        projects: [],
      };
      map[result.orgId].projects.push(result.project);
    }
    return { map, incomplete };
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
    sessionGeneration: number,
  ): Promise<void> {
    const result = await runFlow();
    if (!result.success || !result.data) {
      throw new Error(result.error || fallbackError);
    }

    const session = await this.createSessionFromTokenResponse(result.data, {
      cloudRegion: region,
      selectedProjectId: this.state.currentProjectId,
    });
    await this.syncAuthenticatedSession(session, sessionGeneration);
  }
  private async syncAuthenticatedSession(
    session: InMemorySession,
    sessionGeneration: number,
  ): Promise<boolean> {
    if (this.sessionGeneration !== sessionGeneration) {
      return false;
    }
    if (session.refreshToken) {
      const persisted = await this.persistSession(
        {
          refreshToken: session.refreshToken,
          cloudRegion: session.cloudRegion,
          selectedProjectId: session.currentProjectId,
        },
        () => this.sessionGeneration === sessionGeneration,
      );
      if (!persisted) {
        return false;
      }
    } else {
      this.authSession.clearCurrent();
    }

    if (this.sessionGeneration !== sessionGeneration) {
      return false;
    }
    this.persistProjectPreference(session);
    const desktopAccess = this.carryDesktopAccessInto(session);
    this.session = session;
    this.scheduleImpersonationExpiry(session);
    this.updateState({
      status: "authenticated",
      bootstrapComplete: true,
      cloudRegion: session.cloudRegion,
      orgProjectsMap: session.orgProjectsMap,
      currentOrgId: session.currentOrgId,
      currentProjectId: session.currentProjectId,
      desktopAccess,
      needsScopeReauth: false,
      sessionType: session.sessionType,
      sessionExpiresAt: session.accessTokenExpiresAt,
      sessionEndReason: null,
    });
    await this.updateDesktopAccessFromSession(session);

    if (
      this.sessionGeneration !== sessionGeneration ||
      this.session !== session
    ) {
      return false;
    }
    if (session.orgProjectsIncomplete) {
      void this.refreshOrgProjects();
    }
    return true;
  }
  private async persistSession(
    input: {
      refreshToken: string;
      cloudRegion: CloudRegion;
      selectedProjectId: number | null;
    },
    shouldSave: () => boolean = () => true,
  ): Promise<boolean> {
    const priorSelected =
      this.authSession.getCurrent()?.selectedProjectId ?? null;
    const refreshTokenEncrypted = await this.cipher.encrypt(input.refreshToken);
    if (!shouldSave()) {
      return false;
    }
    this.authSession.saveCurrent({
      refreshTokenEncrypted,
      cloudRegion: input.cloudRegion,
      selectedProjectId: input.selectedProjectId ?? priorSelected,
      scopeVersion: OAUTH_SCOPE_VERSION,
    });
    return true;
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
  ): Promise<{
    accountKey: string | null;
    currentOrgId: string | null;
    orgNames: Record<string, string>;
  }> {
    try {
      const response = await this.executeAuthenticatedFetch(
        fetch,
        `${getCloudUrlFromRegion(cloudRegion)}/api/users/@me/`,
        {},
        accessToken,
      );

      if (!response.ok) {
        return { accountKey: null, currentOrgId: null, orgNames: {} };
      }

      const data = (await response.json().catch(() => ({}))) as {
        uuid?: unknown;
        distinct_id?: unknown;
        email?: unknown;
        organization?: { id?: unknown; name?: unknown } | null;
        organizations?: unknown;
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

      const orgNames: Record<string, string> = {};
      const memberOrgs = Array.isArray(data.organizations)
        ? data.organizations
        : [];
      for (const org of memberOrgs as { id?: unknown; name?: unknown }[]) {
        if (typeof org?.id === "string" && typeof org.name === "string") {
          orgNames[org.id] = org.name;
        }
      }
      if (currentOrgId && typeof data.organization?.name === "string") {
        orgNames[currentOrgId] = data.organization.name;
      }

      return { accountKey, currentOrgId, orgNames };
    } catch (error) {
      this.logger.warn("Failed to resolve user context", { error });
      return { accountKey: null, currentOrgId: null, orgNames: {} };
    }
  }
  private setAnonymousState(
    partial: Pick<
      Partial<AuthState>,
      | "bootstrapComplete"
      | "cloudRegion"
      | "currentProjectId"
      | "needsScopeReauth"
      | "sessionEndReason"
    > = {},
  ): void {
    this.updateState({
      status: "anonymous",
      bootstrapComplete: partial.bootstrapComplete ?? true,
      cloudRegion: partial.cloudRegion ?? null,
      orgProjectsMap: {},
      currentOrgId: null,
      currentProjectId: partial.currentProjectId ?? null,
      desktopAccess: {
        projectId: partial.currentProjectId ?? null,
        status: "unchecked",
        reason: null,
      },
      needsScopeReauth: partial.needsScopeReauth ?? false,
      sessionType: null,
      sessionExpiresAt: null,
      sessionEndReason: partial.sessionEndReason ?? null,
    });
  }

  // Resetting to "checking" on every refresh would unmount the whole app.
  private carryDesktopAccessInto(session: InMemorySession): DesktopAccess {
    const previous = this.state.desktopAccess;
    const previousAccountKey = this.session?.accountKey ?? null;
    // A failed `/api/users/@me/` lookup leaves accountKey null. That is an
    // unknown account, not a different one, so it must not flash the loading
    // screen. A resolved key that differs is a real account change.
    const sameIdentity =
      previousAccountKey !== null &&
      (session.accountKey === null ||
        session.accountKey === previousAccountKey) &&
      previous.projectId === session.currentProjectId;
    if (
      sameIdentity &&
      (previous.status === "allowed" || previous.status === "blocked")
    ) {
      return previous;
    }
    return {
      projectId: session.currentProjectId,
      status: "checking",
      reason: null,
    };
  }

  private async updateDesktopAccessFromSession(
    session: InMemorySession,
  ): Promise<void> {
    const desktopAccess = await this.checkDesktopAccess(session);
    if (this.session !== session) return;
    this.updateState({ desktopAccess });
  }

  private async checkDesktopAccess(
    session: InMemorySession,
  ): Promise<DesktopAccess> {
    const projectId = session.currentProjectId;
    if (projectId === null) {
      return { projectId, status: "error", reason: null };
    }

    if (!this.connectivity.getStatus().isOnline) {
      return { projectId, status: "error", reason: null };
    }

    const url = `${getCloudUrlFromRegion(session.cloudRegion)}/api/projects/${projectId}/desktop/access/`;

    try {
      const response = await this.executeAuthenticatedFetch(
        fetch,
        url,
        {},
        session.accessToken,
      );

      if (response.ok) {
        const result = desktopAccessResponseSchema.safeParse(
          await response.json().catch(() => null),
        );
        if (result.success) {
          if (result.data.allowed) {
            return { projectId, status: "allowed", reason: null };
          }
          return {
            projectId,
            status: "blocked",
            reason: result.data.reason,
          };
        }
        this.logger.warn("Desktop access response was invalid", {
          status: response.status,
        });
      } else {
        this.logger.warn("Desktop access check returned non-OK status", {
          status: response.status,
        });
      }
    } catch (error) {
      this.logger.warn("Desktop access check request failed", { error });
    }

    return { projectId, status: "error", reason: null };
  }
  private static readonly REFRESH_MAX_ATTEMPTS = 3;
  private static readonly ORG_FETCH_MAX_ATTEMPTS = 3;
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
    this.clearImpersonationExpiryTimer();
    this.connectivityUnsubscribe?.();
    this.connectivityUnsubscribe = null;
    this.resumeUnsubscribe?.();
    this.resumeUnsubscribe = null;
  }

  private scheduleImpersonationExpiry(session: InMemorySession): void {
    this.clearImpersonationExpiryTimer();
    if (session.sessionType !== "impersonated") return;

    const delayMs = Math.max(0, session.accessTokenExpiresAt - Date.now());
    this.impersonationExpiryTimer = setTimeout(() => {
      this.impersonationExpiryTimer = null;
      const currentSession = this.session;
      if (
        currentSession?.sessionType === "impersonated" &&
        this.isSessionExpired(currentSession)
      ) {
        this.endImpersonatedSession(currentSession);
      }
    }, delayMs);
  }

  private clearImpersonationExpiryTimer(): void {
    if (this.impersonationExpiryTimer) {
      clearTimeout(this.impersonationExpiryTimer);
      this.impersonationExpiryTimer = null;
    }
  }

  private endImpersonatedSession(session: InMemorySession): void {
    this.sessionGeneration += 1;
    this.clearImpersonationExpiryTimer();
    this.session = null;
    this.refusedRefresh = null;
    this.setAnonymousState({
      cloudRegion: session.cloudRegion,
      currentProjectId: session.currentProjectId,
      sessionEndReason: "impersonation_expired",
    });
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

      let map: OrgProjectsMap;
      let incomplete: boolean;
      if (session.scopedTeamIds.length > 0) {
        const knownOrgNames = Object.fromEntries(
          Object.entries(session.orgProjectsMap)
            .filter(([, org]) => org.orgName !== "(unknown)")
            .map(([orgId, org]) => [orgId, org.orgName]),
        );
        ({ map, incomplete } = await this.buildScopedTeamProjectsMap(
          session.accessToken,
          session.cloudRegion,
          session.scopedTeamIds,
          knownOrgNames,
        ));
      } else {
        const orgIds = Object.keys(session.orgProjectsMap);
        ({ map, incomplete } = await this.buildOrgProjectsMap(
          session.accessToken,
          session.cloudRegion,
          orgIds,
          session.orgProjectsMap,
        ));
      }

      // The session may have been replaced (logout, re-login) while the fetch
      // was in flight; committing the stale one would resurrect it.
      if (this.session !== session) return;

      if (!incomplete) {
        const lastPrefs = session.accountKey
          ? this.authPreference.get(session.accountKey, session.cloudRegion)
          : null;
        const storedSelected =
          this.authSession.getCurrent()?.selectedProjectId ?? null;
        const selection = this.reconcileInitialSelection({
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
          currentOrgId: selection.currentOrgId,
          currentProjectId: selection.currentProjectId,
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
