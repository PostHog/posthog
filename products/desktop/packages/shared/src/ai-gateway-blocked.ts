/** The HTTP statuses a refused PostHog AI gateway route answers with. */
export type GatewayBlockedStatus = 401 | 402 | 403 | 429 | 503;

/**
 * Shared by helper prompts and the agent auth proxy, so agent SDKs classify a
 * refusal the same way on either path.
 */
export const GATEWAY_BLOCKED_ERROR_TYPES: Record<GatewayBlockedStatus, string> =
  {
    401: "authentication_error",
    402: "billing_error",
    403: "permission_error",
    429: "rate_limit_error",
    503: "api_error",
  };

export const GATEWAY_TRANSIENT_DETAIL =
  "Couldn't reach PostHog AI. Retrying shortly.";
