import { getErrorMessage } from "@posthog/shared";

// The single source of truth for the classification set. The runtime schema in
// agent-server.ts builds its enum from this list, so a new category cannot reach
// the union while the schema still rejects it.
export const AGENT_ERROR_CLASSIFICATIONS = [
  "upstream_stream_terminated",
  "upstream_connection_error",
  "upstream_timeout",
  "upstream_provider_failure",
  "upstream_rate_limit",
  "content_block_rejection",
  "turn_ended_without_response",
  "subscription_usage_limit",
  "task_spend_limit",
  "agent_error",
] as const;

export type AgentErrorClassification =
  (typeof AGENT_ERROR_CLASSIFICATIONS)[number];

const RETRYABLE_UPSTREAM_ERROR_CLASSIFICATIONS =
  new Set<AgentErrorClassification>([
    "upstream_stream_terminated",
    "upstream_connection_error",
    "upstream_timeout",
    "upstream_provider_failure",
    "upstream_rate_limit",
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
// A provider that refuses the request for shared capacity rather than for this run: a rate
// limit, a "too many requests" refusal, or a model at capacity. The provider prose carries no
// HTTP status, so the status patterns above miss it and it used to read as a generic
// "agent_error" — indistinguishable from a broken agent body.
//
// Each alternative matches a refusal, not the topic. A bare "rate limited" or "too many
// requests" also appears in an agent's own failure text when the run was reading about someone
// else's rate limiting, and classifying that as upstream would exempt a real defect from the
// failure-streak breaker. A false negative only costs the retry, so the narrower form wins.
//
// The capacity alternative names the model for the same reason. "<subject> is at capacity" is
// also how this product's own throttles read, and a run can surface one of those through a tool
// it called, which reports a failure of the service the run was reading, not of the provider.
const UPSTREAM_RATE_LIMIT_PATTERN =
  /\brate limit (?:exceeded|reached)\b|\bprocessing too many requests\b|\bmodel is at capacity\b/i;
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
  // After the status patterns, so a 429 keeps its established provider-failure category, and
  // after the spend limit, whose own wording quotes a rate limit.
  if (UPSTREAM_RATE_LIMIT_PATTERN.test(text)) {
    return "upstream_rate_limit";
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
    classification === "upstream_timeout" ||
    classification === "upstream_rate_limit"
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
