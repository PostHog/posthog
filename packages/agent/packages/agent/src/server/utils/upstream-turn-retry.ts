import {
  type AgentErrorClassification,
  isRetryableUpstreamErrorClassification,
} from "../../adapters/error-classification";

const MAX_UPSTREAM_TURN_RETRIES = 2;
const UPSTREAM_TURN_RETRY_DELAY_MS = 5_000;
const MAX_RATE_LIMIT_TURN_RETRIES = 4;
const RATE_LIMIT_RETRY_BASE_MS = 15_000;
const RATE_LIMIT_RETRY_CAP_MS = 120_000;
const RATE_LIMIT_RETRY_HINT_CAP_MS = RATE_LIMIT_RETRY_CAP_MS / 2;

export function upstreamTurnRetryDelayMs(
  classification: AgentErrorClassification,
  retries: number,
  retryAfterMs = 0,
  random: () => number = Math.random,
): number | undefined {
  if (!isRetryableUpstreamErrorClassification(classification)) return undefined;
  if (classification !== "upstream_rate_limited") {
    return retries < MAX_UPSTREAM_TURN_RETRIES
      ? UPSTREAM_TURN_RETRY_DELAY_MS
      : undefined;
  }
  if (retries >= MAX_RATE_LIMIT_TURN_RETRIES) return undefined;

  // Reserve jitter even when every run receives the same large retry hint.
  const hint = Math.min(retryAfterMs, RATE_LIMIT_RETRY_HINT_CAP_MS);
  const jitterWindow = Math.min(
    RATE_LIMIT_RETRY_CAP_MS - hint,
    RATE_LIMIT_RETRY_BASE_MS * 2 ** retries,
  );
  return hint + Math.floor(random() * jitterWindow);
}
