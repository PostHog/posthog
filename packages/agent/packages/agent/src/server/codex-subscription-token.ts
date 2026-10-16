import { createHash } from "node:crypto";
import { CHATGPT_AUTH_TOKENS_REFRESH_TIMEOUT_MS } from "../adapters/codex-app-server/protocol";
import type { ChatgptAuthTokens } from "../adapters/codex-app-server/spawn";
import {
  CodexSubscriptionTokenError,
  type CodexSubscriptionTokenErrorCode,
  type PostHogAPIClient,
} from "../posthog-api";
import type { Logger } from "../utils/logger";

/** Ask for a new token this long before the cached one expires. */
export const CODEX_TOKEN_REFRESH_MARGIN_MS = 60_000;
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
}

export const CODEX_SUBSCRIPTION_REFRESH_FAILED_MESSAGES: Record<
  CodexSubscriptionTokenErrorCode,
  string
> = {
  reauth_required:
    "Your ChatGPT login stopped working. Open Desktop, go to Settings > Harness, log in to ChatGPT again, then start the task again.",
  openai_unavailable:
    "OpenAI did not answer the ChatGPT token refresh. Try again in a few minutes.",
  forbidden:
    "This run could not get a new ChatGPT token. Start the task again.",
  request_failed:
    "This run could not get a new ChatGPT token. Start the task again.",
};

export function codexSubscriptionRefreshFailureMessage(error: unknown): string {
  const code: CodexSubscriptionTokenErrorCode =
    error instanceof CodexSubscriptionTokenError
      ? error.code
      : "request_failed";
  return CODEX_SUBSCRIPTION_REFRESH_FAILED_MESSAGES[code];
}

export function accessTokenFingerprint(accessToken: string): string {
  return createHash("sha256").update(accessToken).digest("hex");
}

/**
 * Hands the Codex app-server ChatGPT access tokens for a run on the owner's own
 * plan. The server holds the refresh token and mints a short-lived access
 * token per request; this client only caches the current one and refreshes it
 * before it expires, or when Codex rejects it. A rejection names the rejected
 * token by digest, so the server refreshes once however many runs report it.
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
    return this.fetch(null);
  }

  /** Codex rejected the current token; the server replaces it, or hands back a newer one it already minted. */
  async refresh(): Promise<ChatgptAuthTokens> {
    const rejected = this.cached
      ? accessTokenFingerprint(this.cached.tokens.accessToken)
      : null;
    return this.fetch(rejected);
  }

  private fetch(
    rejectedAccessTokenSha256: string | null,
  ): Promise<ChatgptAuthTokens> {
    if (this.inFlight) return this.inFlight;
    const request = this.request(rejectedAccessTokenSha256).finally(() => {
      this.inFlight = null;
    });
    this.inFlight = request;
    return request;
  }

  private async request(
    rejectedAccessTokenSha256: string | null,
  ): Promise<ChatgptAuthTokens> {
    const grant = await this.options.posthogAPI.requestCodexSubscriptionToken(
      this.options.taskId,
      this.options.runId,
      this.options.runToken,
      rejectedAccessTokenSha256,
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
    };
    this.options.logger?.info("Fetched a ChatGPT access token for this run", {
      afterRejection: rejectedAccessTokenSha256 !== null,
      planType: tokens.chatgptPlanType,
      expiresAt: grant.expires_at,
    });
    return tokens;
  }
}
