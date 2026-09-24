import { ROOT_LOGGER, type RootLogger } from "@posthog/di/logger";
import { validateAiGatewayUrl } from "@posthog/shared";
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

/**
 * Refresh a tenth of the lifetime before expiry, clamped to these bounds, so
 * short tokens do not spend the per-user mint throttle.
 */
export const GATEWAY_TOKEN_REFRESH_SKEW_MS = 2 * 60_000;
export const GATEWAY_TOKEN_MIN_REFRESH_SKEW_MS = 30_000;
export const GATEWAY_LEGACY_RECHECK_MS = 10 * 60_000;
/** `not_rolled_out` changes only with the flag, so it is re-checked less often. */
export const GATEWAY_NOT_ROLLED_OUT_RECHECK_MS = 30 * 60_000;
export const GATEWAY_BLOCKED_RECHECK_MS = 30 * 60_000;
export const GATEWAY_REMINT_MIN_INTERVAL_MS = 5_000;
export const GATEWAY_REFRESH_RETRY_MS = 30_000;

export const GATEWAY_MINT_TIMEOUT_MS = 15_000;

interface CacheEntry {
  route: GatewayRoute;
  recheckAt: number;
  mintedAt: number;
  refreshAt: number;
  inFlight: Promise<GatewayRoute> | null;
  capReminted: Set<string>;
}

/**
 * Holds the app's `phe_` Go gateway token per project, minted through Django
 * and never handed to a subprocess. A refusal routes to the legacy gateway,
 * except an exhausted credit bucket, which is final.
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
   * A due legacy re-check runs in the background unless `awaitRecheck` asks
   * to wait (a session start picks its target once).
   */
  async getRoute(
    projectId?: number | null,
    options: { awaitRecheck?: boolean } = {},
  ): Promise<GatewayRoute> {
    const resolvedProject =
      projectId ?? this.authService.getState().currentProjectId;
    if (resolvedProject === null || resolvedProject === undefined) {
      return { mode: "legacy", reason: "no_project" };
    }
    if (!this.config.goEnabled) {
      return { mode: "legacy", reason: "host_unsupported" };
    }
    if (!this.signedIn) return { mode: "legacy", reason: "signed_out" };
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
   * uses the legacy gateway until the re-check.
   */
  fallBack(token: string, projectId: number | null | undefined): void {
    const resolvedProject =
      projectId ?? this.authService.getState().currentProjectId;
    if (resolvedProject === null || resolvedProject === undefined) return;
    const entry = this.cache.get(resolvedProject);
    if (entry?.route.mode !== "go" || entry.route.token !== token) return;
    this.log.warn("Go refused the gateway token; using the legacy gateway");
    entry.route = { mode: "legacy", reason: "gateway_unauthorized" };
    entry.recheckAt = this.now() + GATEWAY_LEGACY_RECHECK_MS;
  }

  clearBlocked(): void {
    for (const [projectId, entry] of this.cache) {
      if (entry.route.mode === "blocked" && !entry.inFlight) {
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
    // A known legacy refusal is served while it re-checks; a first mint or a
    // blocked route (a hard 402 once its window passes) waits.
    const settled =
      entry !== undefined &&
      entry.route.mode === "legacy" &&
      !isPending(entry.route) &&
      !options.awaitRecheck;
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
      route: { mode: "legacy", reason: "pending" },
      recheckAt: 0,
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
          return { mode: "legacy", reason: "identity_changed" };
        }
        if (
          current?.mode === "go" &&
          route.mode === "legacy" &&
          this.now() < current.expiresAt
        ) {
          this.log.warn(
            "Gateway token refresh failed; keeping the current token",
            { reason: route.reason },
          );
          entry.recheckAt = this.now() + GATEWAY_REFRESH_RETRY_MS;
          return current;
        }
        entry.route = route;
        entry.recheckAt = this.now() + recheckMs;
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
        return this.legacy("identity_changed");
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
      return this.legacy("mint_failed");
    }

    const body: unknown = await response.json().catch(() => null);
    clearTimeout(timer);
    if (response.status !== 201) {
      const refusal = gatewayTokenRefusalSchema.safeParse(body);
      const data = refusal.success ? refusal.data : {};
      const reason = data.reason ?? data.code ?? `http_${response.status}`;
      // Final: the legacy gateway refuses the same user, so no fallback.
      if (response.status === 402 && reason === "credit_bucket_exhausted") {
        this.log.info("Gateway token refused: credit bucket exhausted");
        return {
          route: {
            mode: "blocked",
            reason: "credit_bucket_exhausted",
            detail:
              data.detail ??
              "Your organization has reached its PostHog Desktop usage limit",
          },
          recheckMs: GATEWAY_BLOCKED_RECHECK_MS,
        };
      }
      if (
        reason === "desktop_access_blocked" &&
        generation === this.generation
      ) {
        this.authService.reportDesktopAccessBlocked?.(projectId, data.access);
      }
      this.log.info("Gateway token not issued; using the legacy gateway", {
        status: response.status,
        reason,
      });
      return this.legacy(reason);
    }

    const minted = gatewayTokenMintedSchema.safeParse(body);
    if (!minted.success) {
      this.log.warn("Gateway token response did not match the contract");
      return this.legacy("invalid_mint_response");
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
      return this.legacy("invalid_gateway_url");
    }
    if (!Number.isFinite(expiresAt)) {
      this.log.warn("Gateway token response had an unreadable expiry");
      return this.legacy("invalid_expiry");
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

  private legacy(reason: string): {
    route: GatewayRoute;
    recheckMs: number;
  } {
    return {
      route: { mode: "legacy", reason },
      recheckMs:
        reason === "not_rolled_out"
          ? GATEWAY_NOT_ROLLED_OUT_RECHECK_MS
          : GATEWAY_LEGACY_RECHECK_MS,
    };
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
  return route.mode === "legacy" && route.reason === "pending";
}
