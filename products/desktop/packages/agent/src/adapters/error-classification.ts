import { getErrorMessage } from "@posthog/shared";

export type AgentErrorClassification =
  | "upstream_stream_terminated"
  | "upstream_connection_error"
  | "upstream_timeout"
  | "upstream_provider_failure"
  | "content_block_rejection"
  | "turn_ended_without_response"
  | "subscription_usage_limit"
  | "task_spend_limit"
  | "agent_error";

const RETRYABLE_UPSTREAM_ERROR_CLASSIFICATIONS =
  new Set<AgentErrorClassification>([
    "upstream_stream_terminated",
    "upstream_connection_error",
    "upstream_timeout",
    "upstream_provider_failure",
  ]);

export function isRetryableUpstreamErrorClassification(
  classification: AgentErrorClassification,
): boolean {
  return RETRYABLE_UPSTREAM_ERROR_CLASSIFICATIONS.has(classification);
}

const UPSTREAM_PROVIDER_ERROR_STATUS_PATTERN = /API Error:\s*(?:429|5\d\d)\b/i;
// The codex app-server reports a provider HTTP failure as
// "unexpected status <code> <reason>: <body>" instead of the "API Error:" wording.
const CODEX_PROVIDER_ERROR_STATUS_PATTERN =
  /unexpected status\s*(?:429|5\d\d)\b/i;
const SANDBOX_TASK_SPEND_LIMIT_PATTERN =
  /This agent run reached its spend limit/i;
const TURN_ENDED_WITHOUT_RESPONSE_PATTERN =
  /\[ede_diagnostic\]\s+result_type=user\b/i;
// Anthropic's exact CLI wording for a Claude Pro/Max own-subscription limit
// isn't pinned anywhere we can check offline, so this matches the phrase
// loosely rather than a fixed string. Update this if the real wording turns
// out to differ.
const SUBSCRIPTION_USAGE_LIMIT_PATTERN = /usage limit/i;

/**
 * Classify error strings surfaced by agent adapters. Transient upstream
 * failures are retriable when they match exact stream/connection patterns or
 * retryable provider HTTP statuses; most other errors are not.
 */
export function classifyAgentError(
  result: string | undefined,
): AgentErrorClassification {
  if (!result) return "agent_error";
  const text = result.trim();
  // Anthropic SDK surfaces an undici fetch abort as "API Error: terminated".
  if (/API Error:\s*terminated\b/i.test(text)) {
    return "upstream_stream_terminated";
  }
  // Claude Code surfaces an SSE stream that dies after content started
  // (no message_stop) as "Connection closed mid-response". Seen when a
  // gateway pod is replaced mid-stream or an intermediary cuts the socket
  // during a long silent stretch.
  if (/API Error:.*Connection closed mid-response/i.test(text)) {
    return "upstream_stream_terminated";
  }
  // Transport-level socket deaths reported by fetch implementations
  // (Bun/undici wording varies) — same failure mode as above. These are raw
  // transport errors, so they don't always carry the "API Error:" prefix.
  if (/socket connection (?:was )?closed/i.test(text)) {
    return "upstream_stream_terminated";
  }
  if (/API Error:\s*Connection error\b/i.test(text)) {
    return "upstream_connection_error";
  }
  // An idle cloud sandbox can be reclaimed between turns. A later follow-up
  // reaches the old ACP transport before the host resumes a replacement run.
  if (/^ACP connection closed$/i.test(text)) {
    return "upstream_connection_error";
  }
  if (/API Error:.*\b(?:timed out|timeout)\b/i.test(text)) {
    return "upstream_timeout";
  }
  if (SANDBOX_TASK_SPEND_LIMIT_PATTERN.test(text)) {
    return "task_spend_limit";
  }
  if (
    UPSTREAM_PROVIDER_ERROR_STATUS_PATTERN.test(text) ||
    CODEX_PROVIDER_ERROR_STATUS_PATTERN.test(text)
  ) {
    return "upstream_provider_failure";
  }
  if (/API Error:\s*Content block\b/i.test(text)) {
    return "content_block_rejection";
  }
  if (TURN_ENDED_WITHOUT_RESPONSE_PATTERN.test(text)) {
    return "turn_ended_without_response";
  }
  if (SUBSCRIPTION_USAGE_LIMIT_PATTERN.test(text)) {
    return "subscription_usage_limit";
  }
  return "agent_error";
}

export function sanitizeAgentErrorCause(
  result: string,
  classification: AgentErrorClassification,
): string {
  const text = result.trim();
  const codexStatus = text.match(/\bunexpected status\s+(\d{3})\b/i);
  if (codexStatus) {
    return `unexpected status ${codexStatus[1]}`;
  }
  const apiStatus = text.match(/\bAPI Error:\s*(\d{3})\b/i);
  if (apiStatus) {
    return `API Error: ${apiStatus[1]}`;
  }
  if (
    classification === "upstream_provider_failure" ||
    classification === "upstream_connection_error" ||
    classification === "upstream_stream_terminated" ||
    classification === "upstream_timeout"
  ) {
    return classification;
  }
  return text.slice(0, 400);
}

/**
 * Hard API rejection: the prompt exceeds the model's context window
 * (Anthropic phrasing, or the LLM gateway's HTTP 413). Retrying the same
 * transcript can never succeed; callers must shrink the prompt.
 */
export function isPromptTooLongError(error: unknown): boolean {
  const message = getErrorMessage(error);
  return (
    /prompt is too long/i.test(message) ||
    /exceeded this model context window limit/i.test(message) ||
    /API Error:\s*413\b/i.test(message)
  );
}

// A provider rate limit arrives as a 429 inside `upstream_provider_failure`, the
// same classification as a 5xx. The two need different retry schedules: a 5xx is a
// blip that clears in seconds, a rate limit holds for a window, so the sanitized
// cause is re-read here to tell them apart.
const UPSTREAM_RATE_LIMIT_STATUS_PATTERN =
  /(?:API Error:\s*|unexpected status\s*)429\b/i;

export function isUpstreamRateLimitFailure(
  classification: AgentErrorClassification,
  cause: string | undefined,
): boolean {
  return (
    classification === "upstream_provider_failure" &&
    !!cause &&
    UPSTREAM_RATE_LIMIT_STATUS_PATTERN.test(cause)
  );
}

/**
 * A provider's own "wait this long" hint, in milliseconds, or null when it sent
 * none. OpenAI puts it in the 429 body ("Please try again in 1.5s"); a
 * retry-after header survives when an adapter inlines it into the message. Only
 * the raw message carries this, because sanitizeAgentErrorCause strips the body
 * down to the bare status, so callers must pass the unsanitized text.
 */
export function parseUpstreamRetryAfterMs(
  message: string | undefined,
): number | null {
  if (!message) return null;
  const header = message.match(/retry-after(?:-ms)?["'\s:=]+(\d+(?:\.\d+)?)/i);
  if (header) {
    const value = Number(header[1]);
    // `retry-after-ms` is already milliseconds; bare `retry-after` is seconds.
    return /retry-after-ms/i.test(header[0]) ? value : value * 1000;
  }
  const prose = message.match(
    /try again in\s+(\d+(?:\.\d+)?)\s*(ms|milliseconds?|s|secs?|seconds?|m|mins?|minutes?)\b/i,
  );
  if (prose) {
    const value = Number(prose[1]);
    const unit = prose[2].toLowerCase();
    if (unit.startsWith("ms") || unit.startsWith("milli")) return value;
    if (unit.startsWith("m")) return value * 60_000;
    return value * 1000;
  }
  return null;
}

// Retry schedule for a transient upstream failure. A 5xx keeps the short delay
// this loop was tuned for; a rate limit gets a longer, growing one, because the
// limit window outlives a few seconds and retrying inside it just burns the
// budget. Jitter is what keeps the concurrent unattended runs of one deployment
// from retrying in lockstep and re-tripping the same account-wide limit together.
const UPSTREAM_RETRY_BASE_DELAY_MS = 5_000;
const UPSTREAM_RATE_LIMIT_BASE_DELAY_MS = 20_000;
// Per-wait ceiling. The unattended turn budget has to stay well under the
// dropped-finalization salvage floor (STALE_TURN_SALVAGE_SECONDS, 300s), so a
// backed-off turn is never mistaken for one that fell silent.
const UPSTREAM_RETRY_MAX_DELAY_MS = 45_000;

/**
 * How long to wait before retry number `attempt` (1-based) of a turn that hit
 * `classification`. `message` is the raw, unsanitized error text, read only for
 * a provider retry-after hint. `random` is injectable so tests can pin jitter.
 *
 * A provider's own hint wins over the computed backoff when it asks for longer:
 * it knows when the window clears, and honoring a shorter one would retry while
 * the limit still holds.
 */
export function upstreamRetryDelayMs({
  classification,
  attempt,
  cause,
  message,
  random = Math.random,
}: {
  classification: AgentErrorClassification;
  attempt: number;
  cause?: string;
  message?: string;
  random?: () => number;
}): number {
  const rateLimited = isUpstreamRateLimitFailure(classification, cause);
  const base = rateLimited
    ? UPSTREAM_RATE_LIMIT_BASE_DELAY_MS
    : UPSTREAM_RETRY_BASE_DELAY_MS;
  const exponential = base * 2 ** Math.max(0, attempt - 1);
  const hinted = rateLimited ? parseUpstreamRetryAfterMs(message) : null;
  const target = Math.max(exponential, hinted ?? 0);
  const capped = Math.min(target, UPSTREAM_RETRY_MAX_DELAY_MS);
  // Decorrelated jitter over the lower half of the window, so every run still
  // waits a useful minimum but no two wake at the same instant.
  return Math.round(capped * (0.5 + 0.5 * random()));
}
