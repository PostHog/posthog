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

export type GatewayLimitCause = "model_gate" | "org_limit";

const MODEL_GATE_PATTERNS = ["needs a paid posthog plan"] as const;

const ORG_LIMIT_PATTERNS = [
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
] as const;

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
  if (matches(MODEL_GATE_PATTERNS)) return "model_gate";
  if (matches(ORG_LIMIT_PATTERNS)) return "org_limit";
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

export function isFatalSessionError(
  errorMessage: string,
  errorDetails?: string,
): boolean {
  if (isRateLimitError(errorMessage, errorDetails)) return false;
  if (isTransientUpstreamError(errorMessage, errorDetails)) return false;
  if (classifyGatewayLimitError(errorMessage, errorDetails) === "model_gate") {
    return false;
  }
  return (
    includesAny(errorMessage, FATAL_SESSION_ERROR_PATTERNS) ||
    includesAny(errorDetails, FATAL_SESSION_ERROR_PATTERNS)
  );
}
