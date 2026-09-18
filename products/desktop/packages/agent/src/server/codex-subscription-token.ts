import type { ChatgptAuthTokens } from "../adapters/codex-app-server/spawn";
import { CHATGPT_AUTH_TOKENS_REFRESH_TIMEOUT_MS } from "../adapters/codex-app-server/protocol";
import type { PostHogAPIClient } from "../posthog-api";
import type { Logger } from "../utils/logger";

/** Ask for a new token this long before the cached one expires. */
export const CODEX_TOKEN_REFRESH_MARGIN_MS = 60_000;
/** A token fetched this recently is handed back instead of forcing another refresh. */
export const CODEX_TOKEN_FORCE_COOLDOWN_MS = 30_000;
/** Codex fails the turn if its refresh request is not answered in 10 s. */
export const CODEX_TOKEN_REQUEST_TIMEOUT_MS =
  CHATGPT_AUTH_TOKENS_REFRESH_TIMEOUT_MS - 1_000;

export interface CodexSubscriptionTokenClientOptions {
  posthogAPI: Pick<PostHogAPIClient, "requestCodexSubscriptionToken">;
  taskId: string;
  runId: string;
  runToken: string;
  logger?: Logger;
  now?: () => number;
}

interface CachedGrant {
  tokens: ChatgptAuthTokens;
  expiresAt: number;
  fetchedAt: number;
}

/**
 * Hands the Codex app-server ChatGPT access tokens for a run on the owner's own
 * plan. The server holds the refresh token and mints a short-lived access
 * token per request; this client only caches the current one and refreshes it
 * before it expires, or when Codex rejects it.
 */
export class CodexSubscriptionTokenClient {
  private cached: CachedGrant | null = null;
  private inFlight: Promise<ChatgptAuthTokens> | null = null;
  private readonly now: () => number;

  constructor(private readonly options: CodexSubscriptionTokenClientOptions) {
    this.now = options.now ?? Date.now;
  }

  async get(): Promise<ChatgptAuthTokens> {
    if (
      this.cached &&
      this.cached.expiresAt - CODEX_TOKEN_REFRESH_MARGIN_MS > this.now()
    ) {
      return this.cached.tokens;
    }
    return this.fetch(false);
  }

  /** Codex rejected the current token; a stale one is replaced, a fresh one is retried. */
  async refresh(): Promise<ChatgptAuthTokens> {
    if (
      this.cached &&
      this.now() - this.cached.fetchedAt < CODEX_TOKEN_FORCE_COOLDOWN_MS
    ) {
      return this.cached.tokens;
    }
    return this.fetch(true);
  }

  private fetch(force: boolean): Promise<ChatgptAuthTokens> {
    if (this.inFlight) return this.inFlight;
    const request = this.request(force).finally(() => {
      this.inFlight = null;
    });
    this.inFlight = request;
    return request;
  }

  private async request(force: boolean): Promise<ChatgptAuthTokens> {
    const grant = await this.options.posthogAPI.requestCodexSubscriptionToken(
      this.options.taskId,
      this.options.runId,
      this.options.runToken,
      force,
      CODEX_TOKEN_REQUEST_TIMEOUT_MS,
    );
    const tokens: ChatgptAuthTokens = {
      accessToken: grant.access_token,
      chatgptAccountId: grant.account_id,
      chatgptPlanType: grant.plan_type ?? undefined,
    };
    const expiresAt = Date.parse(grant.expires_at);
    this.cached = {
      tokens,
      expiresAt: Number.isNaN(expiresAt) ? this.now() : expiresAt,
      fetchedAt: this.now(),
    };
    this.options.logger?.info("Fetched a ChatGPT access token for this run", {
      force,
      planType: tokens.chatgptPlanType,
      expiresAt: grant.expires_at,
    });
    return tokens;
  }
}
