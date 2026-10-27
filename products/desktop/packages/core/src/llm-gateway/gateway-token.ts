import { ROOT_LOGGER, type RootLogger } from "@posthog/di/logger";
import {
  GATEWAY_TRANSIENT_DETAIL,
  validateAiGatewayUrl,
} from "@posthog/shared";
import { inject, injectable } from "inversify";
import type { AuthService } from "../auth/auth";
import { AUTH_SERVICE } from "../auth/auth.module";
import { AuthServiceEvent, type AuthState } from "../auth/schemas";
import {
  GATEWAY_TOKEN_HOST,
  type GatewayTokenHost,
  LLM_GATEWAY_HOST,
  type LlmGatewayHost,
  type LlmGatewayLogger,
} from "./identifiers";
import {
  type GatewayRemintReason,
  type GatewayRoute,
  gatewayTokenMintedSchema,
  gatewayTokenRefusalSchema,
} from "./schemas";

type GoRoute = Extract<GatewayRoute, { mode: "go" }>;
type BlockedRoute = Extract<GatewayRoute, { mode: "blocked" }>;

/**
 * Refresh a tenth of the lifetime before expiry, clamped to these bounds, so
 * short tokens do not spend the per-user mint throttle.
 */
export const GATEWAY_TOKEN_REFRESH_SKEW_MS = 2 * 60_000;
export const GATEWAY_TOKEN_MIN_REFRESH_SKEW_MS = 30_000;
/** A refusal the user can clear (verify email, sign in again). */
export const GATEWAY_ACTION_RECHECK_MS = 10 * 60_000;
export const GATEWAY_BLOCKED_RECHECK_MS = 30 * 60_000;
export const GATEWAY_THROTTLED_RECHECK_MS = 5 * 60_000;
export const GATEWAY_TRANSIENT_RECHECK_MS = 30_000;
export const GATEWAY_TRANSIENT_MAX_RECHECK_MS = 10 * 60_000;
export const GATEWAY_REMINT_MIN_INTERVAL_MS = 5_000;

export const GATEWAY_MINT_TIMEOUT_MS = 15_000;

const SIGN_IN_DETAIL = "Sign in to PostHog again to use PostHog AI.";

interface RefusalPolicy {
  status: BlockedRoute["status"];
  recheckMs: number;
  /** Used when the server sends no detail; transient refusals always use it. */
  detail: string;
  serverDetail: boolean;
}

const TRANSIENT: RefusalPolicy = {
  status: 503,
  recheckMs: GATEWAY_TRANSIENT_RECHECK_MS,
  detail: GATEWAY_TRANSIENT_DETAIL,
  serverDetail: false,
};

const UNAVAILABLE: RefusalPolicy = {
  status: 403,
  recheckMs: GATEWAY_ACTION_RECHECK_MS,
  detail: "PostHog AI isn't available for this project right now.",
  serverDetail: true,
};

const REFUSALS: Record<string, RefusalPolicy> = {
  credit_bucket_exhausted: {
    status: 402,
    recheckMs: GATEWAY_BLOCKED_RECHECK_MS,
    detail: "Your organization has reached its PostHog Desktop usage limit",
    serverDetail: true,
  },
  throttled: {
    status: 429,
    recheckMs: GATEWAY_THROTTLED_RECHECK_MS,
    detail: "Too many PostHog AI sign-in attempts. Try again in a few minutes.",
    serverDetail: false,
  },
  email_unverified: {
    status: 403,
    recheckMs: GATEWAY_ACTION_RECHECK_MS,
    detail: "Verify your email to use PostHog AI.",
    serverDetail: true,
  },
  oauth_required: {
    status: 401,
    recheckMs: GATEWAY_ACTION_RECHECK_MS,
    detail: SIGN_IN_DETAIL,
    serverDetail: true,
  },
  unauthorized: {
    status: 401,
    recheckMs: GATEWAY_ACTION_RECHECK_MS,
    detail: SIGN_IN_DETAIL,
    serverDetail: true,
  },
  signed_out: {
    status: 401,
    recheckMs: GATEWAY_ACTION_RECHECK_MS,
    detail: SIGN_IN_DETAIL,
    serverDetail: false,
  },
  blocked: {
    status: 403,
    recheckMs: GATEWAY_BLOCKED_RECHECK_MS,
    detail: "This account can't use PostHog AI.",
    serverDetail: true,
  },
  desktop_access_blocked: {
    status: 403,
    recheckMs: GATEWAY_BLOCKED_RECHECK_MS,
    detail: "PostHog Desktop access is required.",
    serverDetail: true,
  },
  no_project: {
    status: 403,
    recheckMs: GATEWAY_ACTION_RECHECK_MS,
    detail: "Select a project to use PostHog AI.",
    serverDetail: false,
  },
  // Go sends no CORS headers, so the web host cannot reach it.
  host_unsupported: {
    status: 403,
    recheckMs: GATEWAY_BLOCKED_RECHECK_MS,
    detail: "PostHog AI helpers aren't available in the web app yet.",
    serverDetail: false,
  },
  unconfigured: UNAVAILABLE,
  not_rolled_out: UNAVAILABLE,
  org_deactivated: UNAVAILABLE,
  organization_deactivated: UNAVAILABLE,
};

/**
 * An unlisted reason falls back on the HTTP status: a 4xx keeps the server's
 * detail, anything else is transient.
 */
function policyFor(reason: string, httpStatus?: number): RefusalPolicy {
  // Own keys only: the reason comes from the response body.
  if (Object.hasOwn(REFUSALS, reason)) {
    return REFUSALS[reason];
  }
  if (httpStatus === 429) return REFUSALS.throttled;
  if (httpStatus !== undefined && httpStatus >= 400 && httpStatus < 500) {
    return {
      ...UNAVAILABLE,
      status: httpStatus === 401 || httpStatus === 402 ? httpStatus : 403,
    };
  }
  return TRANSIENT;
}

export function blockedRoute(
  reason: string,
  serverDetail?: string,
  httpStatus?: number,
): { route: BlockedRoute; recheckMs: number } {
  const policy = policyFor(reason, httpStatus);
  const detail =
    policy.serverDetail && serverDetail ? serverDetail : policy.detail;
  return {
    route: { mode: "blocked", reason, detail, status: policy.status },
    recheckMs: policy.recheckMs,
  };
}

/**
 * The re-check after the `failures`th transient refusal in a row: doubles from
 * 30s up to the cap, and jitter only shortens it so clients spread out.
 */
export function transientRecheckMs(failures: number, random: number): number {
  const ceiling = Math.min(
    GATEWAY_TRANSIENT_RECHECK_MS * 2 ** Math.max(0, failures - 1),
    GATEWAY_TRANSIENT_MAX_RECHECK_MS,
  );
  return Math.round(ceiling * (0.5 + random * 0.5));
}

function isTransient(route: GatewayRoute): boolean {
  return route.mode === "blocked" && route.status === 503;
}

interface CacheEntry {
  route: GatewayRoute;
  recheckAt: number;
  /** Consecutive transient refusals, reset by any other outcome. */
  transientFailures: number;
  mintedAt: number;
  refreshAt: number;
  inFlight: Promise<GatewayRoute> | null;
  capReminted: Set<string>;
}

/**
 * Holds the app's `phe_` Go gateway token per project, minted through Django
 * and never handed to a subprocess. A refusal blocks the project with a reason
 * until its re-check.
 */
@injectable()
export class GatewayTokenService {
  private readonly cache = new Map<number, CacheEntry>();
  // Bumped on sign-out and on an account or region switch; a mint started
  // under an older value is never cached or returned.
  private generation = 0;
  private signedIn = false;
  private region: string | null = null;
  private account: string | null = null;
  private epoch: number | null = null;
  private routesKey = "";
  private readonly log: LlmGatewayLogger;
  private readonly now: () => number = () => Date.now();
  private readonly random: () => number = () => Math.random();

  constructor(
    @inject(LLM_GATEWAY_HOST)
    private readonly host: LlmGatewayHost,
    @inject(GATEWAY_TOKEN_HOST)
    private readonly config: GatewayTokenHost,
    @inject(AUTH_SERVICE)
    private readonly authService: AuthService,
    @inject(ROOT_LOGGER)
    logger: RootLogger,
  ) {
    this.log = logger.scope("gateway-token");
    this.handleAuthState(authService.getState());
    authService.on(AuthServiceEvent.StateChanged, (state) =>
      this.handleAuthState(state),
    );
  }

  /**
   * A due re-check of a blocked route is awaited unless `awaitRecheck` is
   * false, which serves the blocked route and re-checks in the background.
   */
  async getRoute(
    projectId?: number | null,
    options: { awaitRecheck?: boolean } = {},
  ): Promise<GatewayRoute> {
    const resolvedProject =
      projectId ?? this.authService.getState().currentProjectId;
    if (resolvedProject === null || resolvedProject === undefined) {
      return blockedRoute("no_project").route;
    }
    if (!this.config.goEnabled) {
      return blockedRoute("host_unsupported").route;
    }
    if (!this.signedIn) return blockedRoute("signed_out").route;
    return this.routeFor(resolvedProject, options);
  }

  async remint(
    reason: GatewayRemintReason,
    staleToken: string,
    projectId: number | null | undefined,
  ): Promise<GatewayRoute | null> {
    const resolvedProject =
      projectId ?? this.authService.getState().currentProjectId;
    if (resolvedProject === null || resolvedProject === undefined) return null;
    if (this.config.override) return null;
    if (!this.signedIn) return null;
    const entry = this.cache.get(resolvedProject);
    if (entry?.inFlight) {
      const route = await entry.inFlight;
      return route.mode === "go" && route.token !== staleToken ? route : null;
    }
    if (entry?.route.mode === "go" && entry.route.token !== staleToken) {
      return entry.route;
    }
    if (entry?.route.mode === "blocked" && this.now() < entry.recheckAt) {
      return null;
    }
    if (reason === "token_cap_exceeded" && entry?.capReminted.has(staleToken)) {
      return null;
    }
    if (entry && this.now() - entry.mintedAt < GATEWAY_REMINT_MIN_INTERVAL_MS) {
      if (reason === "unauthorized") this.fallBack(staleToken, resolvedProject);
      return null;
    }
    if (reason === "token_cap_exceeded") entry?.capReminted.add(staleToken);
    const route = await this.mint(resolvedProject);
    return route.mode === "go" ? route : null;
  }

  /**
   * Go refused `token` with a 401 and no re-mint can replace it: the project
   * is blocked until a short re-check mints again.
   */
  fallBack(token: string, projectId: number | null | undefined): void {
    const resolvedProject =
      projectId ?? this.authService.getState().currentProjectId;
    if (resolvedProject === null || resolvedProject === undefined) return;
    const entry = this.cache.get(resolvedProject);
    if (entry?.route.mode !== "go" || entry.route.token !== token) return;
    this.log.warn("Go refused the gateway token; blocking until a re-mint");
    // 503, not 401: the block clears on a re-mint, and agent SDKs retry a 5xx
    // but give up on a 401.
    entry.route = {
      mode: "blocked",
      reason: "gateway_unauthorized",
      detail: "PostHog AI couldn't verify this session. Retrying shortly.",
      status: 503,
    };
    this.scheduleRecheck(entry, entry.route, GATEWAY_TRANSIENT_RECHECK_MS);
  }

  /** Usage reports credit left, which disproves only an exhausted bucket. */
  clearBlocked(): void {
    for (const [projectId, entry] of this.cache) {
      if (
        entry.route.mode === "blocked" &&
        entry.route.reason === "credit_bucket_exhausted" &&
        !entry.inFlight
      ) {
        this.cache.delete(projectId);
      }
    }
  }

  private routeFor(
    projectId: number,
    options: { awaitRecheck?: boolean },
  ): Promise<GatewayRoute> | GatewayRoute {
    const override = this.overrideRoute(projectId);
    if (override) return override;

    const entry = this.cache.get(projectId);
    const now = this.now();
    // A known refusal is served while it re-checks only for a caller that
    // opts out of waiting; a first mint always waits.
    const settled =
      entry !== undefined &&
      !isPending(entry.route) &&
      options.awaitRecheck === false;
    if (entry?.inFlight && entry.route.mode !== "go") {
      return settled ? entry.route : entry.inFlight;
    }
    if (entry?.route.mode === "go") {
      const { expiresAt } = entry.route;
      if (now < entry.refreshAt) return entry.route;
      if (now < expiresAt) {
        if (now >= entry.recheckAt) {
          void this.mint(projectId, true).catch(() => undefined);
        }
        return entry.route;
      }
      return this.mint(projectId);
    }
    if (entry && now < entry.recheckAt) return entry.route;
    if (settled) {
      void this.mint(projectId).catch(() => undefined);
      return entry.route;
    }
    return this.mint(projectId);
  }

  private mint(
    projectId: number,
    keepValidToken = false,
  ): Promise<GatewayRoute> {
    const existing = this.cache.get(projectId);
    if (existing?.inFlight) return existing.inFlight;
    const current = keepValidToken ? existing?.route : undefined;
    const entry: CacheEntry = existing ?? {
      route: blockedRoute("pending").route,
      recheckAt: 0,
      transientFailures: 0,
      mintedAt: 0,
      refreshAt: 0,
      inFlight: null,
      capReminted: new Set(),
    };
    entry.mintedAt = this.now();
    const generation = this.generation;
    const inFlight = this.requestMint(projectId, generation)
      .then(({ route, recheckMs }): GatewayRoute => {
        if (generation !== this.generation) {
          return blockedRoute("identity_changed").route;
        }
        // An exhausted bucket is final; any other refusal keeps a live token.
        if (
          current?.mode === "go" &&
          route.mode === "blocked" &&
          route.reason !== "credit_bucket_exhausted" &&
          this.now() < current.expiresAt
        ) {
          this.log.warn(
            "Gateway token refresh failed; keeping the current token",
            { reason: route.reason },
          );
          // Past expiry `routeFor` mints regardless, so a long window only
          // stops early refresh attempts.
          this.scheduleRecheck(entry, route, recheckMs);
          return current;
        }
        entry.route = route;
        this.scheduleRecheck(entry, route, recheckMs);
        if (route.mode === "go") {
          const lifetime = route.expiresAt - this.now();
          entry.refreshAt =
            route.expiresAt -
            Math.min(
              GATEWAY_TOKEN_REFRESH_SKEW_MS,
              Math.max(GATEWAY_TOKEN_MIN_REFRESH_SKEW_MS, lifetime / 10),
            );
        }
        return route;
      })
      .finally(() => {
        entry.inFlight = null;
      });
    entry.inFlight = inFlight;
    this.cache.set(projectId, entry);
    return inFlight;
  }

  private async requestMint(
    projectId: number,
    generation: number,
  ): Promise<{ route: GatewayRoute; recheckMs: number }> {
    let apiHost: string;
    let response: Response;
    // Covers the mint request and its body, not the OAuth token read.
    const timeout = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      ({ apiHost } = await this.host.getValidAccessToken());
      // The OAuth token read above may already belong to the next identity.
      if (generation !== this.generation)
        return blockedRoute("identity_changed");
      timer = setTimeout(() => timeout.abort(), GATEWAY_MINT_TIMEOUT_MS);
      response = await this.host.authenticatedFetch(
        `${apiHost}/api/projects/${projectId}/desktop/gateway_token/`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: "{}",
          redirect: "error",
          signal: timeout.signal,
        },
      );
    } catch (error) {
      this.log.warn("Gateway token mint failed", {
        error: error instanceof Error ? error.message : String(error),
        timedOut: timeout.signal.aborted,
      });
      clearTimeout(timer);
      return blockedRoute("mint_failed");
    }

    const body: unknown = await response.json().catch(() => null);
    clearTimeout(timer);
    if (response.status !== 201) {
      const refusal = gatewayTokenRefusalSchema.safeParse(body);
      const data = refusal.success ? refusal.data : {};
      const reason = data.reason ?? data.code ?? `http_${response.status}`;
      if (
        reason === "desktop_access_blocked" &&
        generation === this.generation
      ) {
        this.authService.reportDesktopAccessBlocked?.(projectId, data.access);
      }
      this.log.info("Gateway token not issued", {
        status: response.status,
        reason,
      });
      return blockedRoute(reason, data.detail, response.status);
    }

    const minted = gatewayTokenMintedSchema.safeParse(body);
    if (!minted.success) {
      this.log.warn("Gateway token response did not match the contract");
      return blockedRoute("invalid_mint_response");
    }
    const gatewayUrl = validateAiGatewayUrl(minted.data.gateway_url, {
      apiHost,
    });
    // Read against the server's clock, so a skewed local clock neither
    // expires a fresh token nor keeps a dead one.
    const serverNow = Date.parse(response.headers.get("date") ?? "");
    const expiresAt =
      Date.parse(minted.data.expires_at) -
      (Number.isFinite(serverNow) ? serverNow : this.now()) +
      this.now();
    if (!gatewayUrl) {
      this.log.warn("Gateway token response named an untrusted gateway");
      return blockedRoute("invalid_gateway_url");
    }
    if (!Number.isFinite(expiresAt)) {
      this.log.warn("Gateway token response had an unreadable expiry");
      return blockedRoute("invalid_expiry");
    }
    return {
      route: {
        mode: "go",
        gatewayUrl,
        token: minted.data.token,
        expiresAt,
        capUsd: minted.data.cap_usd,
        allowedModels: minted.data.allowed_models,
        productModels: minted.data.product_models,
        plan: minted.data.plan,
        projectId,
        teamId: minted.data.team_id,
        source: "mint",
      },
      recheckMs: 0,
    };
  }

  private scheduleRecheck(
    entry: CacheEntry,
    route: GatewayRoute,
    recheckMs: number,
  ): void {
    if (isTransient(route)) {
      entry.transientFailures += 1;
      entry.recheckAt =
        this.now() + transientRecheckMs(entry.transientFailures, this.random());
      return;
    }
    entry.transientFailures = 0;
    entry.recheckAt = this.now() + recheckMs;
  }

  private overrideRoute(projectId: number): GoRoute | null {
    const override = this.config.override;
    if (!override) return null;
    return {
      mode: "go",
      gatewayUrl: override.url,
      token: override.token,
      expiresAt: Number.POSITIVE_INFINITY,
      capUsd: "",
      allowedModels: null,
      productModels: [],
      plan: "paid",
      projectId,
      teamId: projectId,
      source: "override",
    };
  }

  private handleAuthState(state: AuthState): void {
    if (state.status === "anonymous") {
      if (this.signedIn) this.generation += 1;
      this.signedIn = false;
      this.account = null;
      this.epoch = null;
      this.cache.clear();
      return;
    }
    if (state.status !== "authenticated") return;
    // A null account is a failed lookup, not a different account; the
    // session epoch still catches a sign-in over a live session.
    const account = this.authService.getCachedAccountKey?.() ?? null;
    const epoch = this.authService.getSessionEpoch?.() ?? null;
    const identityChanged =
      !this.signedIn ||
      state.cloudRegion !== this.region ||
      (epoch !== null && this.epoch !== null && epoch !== this.epoch) ||
      (account !== null && this.account !== null && account !== this.account);
    if (account !== null) this.account = account;
    if (epoch !== null) this.epoch = epoch;
    const routesKey = JSON.stringify([
      state.currentOrgId,
      state.currentProjectId,
      state.sessionType,
    ]);
    if (identityChanged) {
      this.generation += 1;
      this.signedIn = true;
      this.region = state.cloudRegion;
    }
    if (identityChanged || routesKey !== this.routesKey) this.cache.clear();
    this.routesKey = routesKey;
  }
}

function isPending(route: GatewayRoute): boolean {
  return route.mode === "blocked" && route.reason === "pending";
}
