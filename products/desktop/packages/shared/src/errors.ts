export class NotAuthenticatedError extends Error {
  constructor(message = "Not authenticated") {
    super(message);
    this.name = "NotAuthenticatedError";
  }
}

export function isNotAuthenticatedError(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    (error as { name?: unknown }).name === "NotAuthenticatedError"
  );
}

const AUTH_ERROR_PATTERNS = [
  "authentication required",
  "failed to authenticate",
  "authentication_error",
  "authentication_failed",
  "access token has expired",
] as const;

export function getErrorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  if (typeof error === "object" && error !== null && "message" in error) {
    return String((error as { message: unknown }).message);
  }
  return "";
}

export interface SerializedError {
  name?: string;
  message: string;
  code?: string | number;
  cause?: SerializedError;
}

export function serializeError(error: unknown, maxDepth = 5): SerializedError {
  if (typeof error === "object" && error !== null) {
    const source = error as {
      name?: unknown;
      message?: unknown;
      code?: unknown;
      cause?: unknown;
    };
    const result: SerializedError = {
      message:
        typeof source.message === "string" ? source.message : String(error),
    };
    if (typeof source.name === "string") {
      result.name = source.name;
    }
    if (typeof source.code === "string" || typeof source.code === "number") {
      result.code = source.code;
    }
    if (source.cause != null && maxDepth > 0) {
      result.cause = serializeError(source.cause, maxDepth - 1);
    }
    return result;
  }
  return { message: String(error) };
}

export function isAuthError(error: unknown): boolean {
  const message = getErrorMessage(error).toLowerCase();
  if (!message) return false;
  return AUTH_ERROR_PATTERNS.some((pattern) => message.includes(pattern));
}

const RATE_LIMIT_PATTERNS = [
  "rate limit exceeded",
  "rate_limit",
  "[429]",
] as const;

export type GatewayLimitCause =
  | "model_gate"
  | "model_unavailable"
  | "org_limit";

const MODEL_GATE_CODE_REGEX = /"code"\s*:\s*"model_gate"/;
const AI_GATEWAY_MODEL_GATE_REGEX =
  /\b(?:model_not_allowed|effort_not_allowed)\b/i;
const AI_GATEWAY_ORG_LIMIT_REGEX =
  /\b(?:cap_exceeded|token_cap_exceeded|insufficient_credits|credit_bucket_exhausted|budget_exceeded)\b/i;
// Go writes these phrases for outages and auth failures too, so they count
// only after the refusal's own status.
const AI_GATEWAY_ROUTER_REFUSAL_REGEX =
  /\b400\b[\s\S]*router rejected request/i;
const AI_GATEWAY_ADMISSION_REFUSAL_REGEX = /\b402\b[\s\S]*admission rejected/i;
// Anthropic-dialect bodies carry no code, only this fixed 403 text.
const AI_GATEWAY_PIN_REFUSAL_REGEX =
  /\b403\b[\s\S]*(?:not allowed for this credential|this credential requires an explicit reasoning effort)/i;
const MODEL_UNAVAILABLE_REASON_REGEX = /"reason"\s*:\s*"model_not_available"/;

const MODEL_GATE_PATTERNS = ["needs a paid posthog plan"] as const;

const MODEL_UNAVAILABLE_PATTERNS = [
  "is not available for your account",
  "is not available. choose another model. (rate_limit)",
] as const;

const ORG_LIMIT_PATTERNS = [
  "cloud usage limit reached",
  "reached its posthog desktop usage limit",
  // Older gateway deployments still send the pre-rename wording.
  "reached its posthog code usage limit",
  "reached its usage limit for this billing period",
  // Per-user free valves — billed orgs have none, so these always mean the
  // free tier is used up.
  "user burst rate limit exceeded",
  "user sustained rate limit exceeded",
] as const;

const FATAL_SESSION_ERROR_PATTERNS = [
  "internal error",
  "process exited",
  "session did not end",
  "not ready for writing",
  "session not found",
] as const;

const REQUEST_SIZE_ERROR_PATTERNS = [
  "this conversation is too large to continue",
  "request body too large",
  "payload too large",
  "prompt is too long",
  "exceeded this model context window limit",
] as const;

const REQUEST_SIZE_ERROR_REGEX = /API Error:\s*413\b/i;

/**
 * Transient upstream provider failures, as surfaced by agent adapters in
 * "API Error: …" result strings (kept in sync with classifyAgentError in
 * @posthog/agent). The agent process and session are healthy — a single
 * provider request timed out, dropped, or returned a retryable status — so
 * these must not count as fatal session errors: the fix is re-sending the
 * prompt, never tearing the session down. Checked before the fatal patterns
 * because the ACP layer wraps them as "Internal error: API Error: …".
 */
const UPSTREAM_TRANSIENT_ERROR_REGEXES = [
  /API Error:\s*terminated\b/i,
  /API Error:\s*Connection error\b/i,
  /API Error:.*Connection closed mid-response/i,
  // Raw transport-level socket death — wording varies by fetch
  // implementation and doesn't always carry the "API Error:" prefix.
  /socket connection (?:was )?closed/i,
  /API Error:.*\b(?:timed out|timeout)\b/i,
  /API Error:\s*(?:429|5\d\d)\b/i,
  // The provider refuses a turn whose transcript content blocks do not line up
  // ("Content block not found", "Content block is not a thinking block"). The
  // wording changes with the provider, so match the family, not each string.
  /API Error:\s*Content block\b/i,
] as const;

const TURN_ENDED_WITHOUT_RESPONSE_REGEX =
  /\[ede_diagnostic\]\s+result_type=user\b/i;

function includesAny(
  value: string | undefined,
  patterns: readonly string[],
): boolean {
  if (!value) return false;
  const lower = value.toLowerCase();
  return patterns.some((pattern) => lower.includes(pattern));
}

export function isRateLimitError(
  errorMessage: string,
  errorDetails?: string,
): boolean {
  return (
    includesAny(errorMessage, RATE_LIMIT_PATTERNS) ||
    includesAny(errorDetails, RATE_LIMIT_PATTERNS)
  );
}

export function classifyGatewayLimitError(
  errorMessage: string,
  errorDetails?: string,
): GatewayLimitCause | null {
  const matches = (patterns: readonly string[]) =>
    includesAny(errorMessage, patterns) || includesAny(errorDetails, patterns);
  const matchesRegex = (regex: RegExp) =>
    regex.test(errorMessage) || (!!errorDetails && regex.test(errorDetails));
  if (
    matchesRegex(MODEL_UNAVAILABLE_REASON_REGEX) ||
    matches(MODEL_UNAVAILABLE_PATTERNS)
  ) {
    return "model_unavailable";
  }
  if (
    matchesRegex(MODEL_GATE_CODE_REGEX) ||
    matches(MODEL_GATE_PATTERNS) ||
    matchesRegex(AI_GATEWAY_MODEL_GATE_REGEX) ||
    matchesRegex(AI_GATEWAY_PIN_REFUSAL_REGEX) ||
    matchesRegex(AI_GATEWAY_ROUTER_REFUSAL_REGEX)
  ) {
    return "model_gate";
  }
  if (
    matches(ORG_LIMIT_PATTERNS) ||
    matchesRegex(AI_GATEWAY_ORG_LIMIT_REGEX) ||
    matchesRegex(AI_GATEWAY_ADMISSION_REFUSAL_REGEX)
  ) {
    return "org_limit";
  }
  return null;
}

export function aiGatewayDenialCode(
  denialHeader: string | null | undefined,
  body: unknown,
): string | undefined {
  const fromHeader = denialHeader?.split(":")[0]?.trim();
  if (fromHeader) return fromHeader;
  let parsed = body;
  if (typeof body === "string") {
    try {
      parsed = JSON.parse(body);
    } catch {
      return undefined;
    }
  }
  if (!parsed || typeof parsed !== "object") return undefined;
  const envelope = parsed as { code?: unknown; error?: { code?: unknown } };
  const candidate = envelope.error?.code ?? envelope.code;
  return typeof candidate === "string" ? candidate : undefined;
}

/**
 * Whether a fresh Go token can fix a refusal: a 401, or a 402 for the token's
 * own cap (the org's limits are refused again after a re-mint).
 */
export function aiGatewayRemintReason(
  status: number | undefined,
  denialCode: string | undefined,
): "unauthorized" | "token_cap_exceeded" | null {
  if (status === 401) return "unauthorized";
  if (status === 402 && denialCode === "token_cap_exceeded") {
    return "token_cap_exceeded";
  }
  return null;
}

export function isTransientUpstreamError(
  errorMessage: string,
  errorDetails?: string,
): boolean {
  return UPSTREAM_TRANSIENT_ERROR_REGEXES.some(
    (regex) =>
      regex.test(errorMessage) || (!!errorDetails && regex.test(errorDetails)),
  );
}

export function isTurnEndedWithoutResponseError(
  errorMessage: string,
  errorDetails?: string,
): boolean {
  return (
    TURN_ENDED_WITHOUT_RESPONSE_REGEX.test(errorMessage) ||
    (!!errorDetails && TURN_ENDED_WITHOUT_RESPONSE_REGEX.test(errorDetails))
  );
}

export type PromptFailureKind =
  | "usage_limit"
  | "transient"
  | "authentication"
  | "fatal_session"
  | "unknown";

export interface PromptFailure {
  kind: PromptFailureKind;
  message: string;
  retryable: boolean;
  limitCause: GatewayLimitCause | null;
}

export function classifyPromptFailure(
  error: unknown,
  errorDetails?: string,
  errorType?: string,
): PromptFailure {
  const message = getErrorMessage(error) || String(error);
  const limitCause = classifyGatewayLimitError(message, errorDetails);
  if (limitCause !== null || isRateLimitError(message, errorDetails)) {
    return {
      kind: "usage_limit",
      message,
      retryable: false,
      limitCause,
    };
  }
  if (
    errorType === "turn_ended_without_response" ||
    isTurnEndedWithoutResponseError(message, errorDetails)
  ) {
    return {
      kind: "transient",
      message,
      retryable: true,
      limitCause: null,
    };
  }
  if (
    errorType?.startsWith("upstream_") ||
    isTransientUpstreamError(message, errorDetails)
  ) {
    return {
      kind: "transient",
      message,
      retryable: true,
      limitCause: null,
    };
  }
  if (isNotAuthenticatedError(error) || isAuthError(error)) {
    return {
      kind: "authentication",
      message,
      retryable: true,
      limitCause: null,
    };
  }
  if (isFatalSessionError(message, errorDetails)) {
    return {
      kind: "fatal_session",
      message,
      retryable: true,
      limitCause: null,
    };
  }
  return {
    kind: "unknown",
    message,
    retryable: false,
    limitCause: null,
  };
}

export function isFatalSessionError(
  errorMessage: string,
  errorDetails?: string,
): boolean {
  if (
    includesAny(errorMessage, REQUEST_SIZE_ERROR_PATTERNS) ||
    includesAny(errorDetails, REQUEST_SIZE_ERROR_PATTERNS) ||
    REQUEST_SIZE_ERROR_REGEX.test(errorMessage) ||
    REQUEST_SIZE_ERROR_REGEX.test(errorDetails ?? "")
  ) {
    return false;
  }
  if (isRateLimitError(errorMessage, errorDetails)) return false;
  if (isTurnEndedWithoutResponseError(errorMessage, errorDetails)) return false;
  if (isTransientUpstreamError(errorMessage, errorDetails)) return false;
  if (classifyGatewayLimitError(errorMessage, errorDetails) !== null) {
    return false;
  }
  return (
    includesAny(errorMessage, FATAL_SESSION_ERROR_PATTERNS) ||
    includesAny(errorDetails, FATAL_SESSION_ERROR_PATTERNS)
  );
}
