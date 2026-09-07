import { CLOUD_REGIONS } from "@posthog/shared";
import { z } from "zod";

export const cloudRegion = z.enum(CLOUD_REGIONS);
export type CloudRegion = z.infer<typeof cloudRegion>;

/**
 * Serialized deployment target for a session: an ordinary region by value, or
 * `"preview"` for a desktop-preview deployment (whose origin and client id come
 * from the build's injected `AUTH_PREVIEW_DEPLOYMENT` manifest, so the wire
 * value stays opaque). Existing ordinary sessions keep their exact serialized
 * values; `"preview"` never resolves to a production URL.
 */
export const deploymentTarget = z.enum([...CLOUD_REGIONS, "preview"]);
export type DeploymentTarget = z.infer<typeof deploymentTarget>;

/**
 * Error codes for OAuth operations.
 * - network_error: Transient network issue, should retry
 * - server_error: Server error (5xx), should retry
 * - auth_error: Authentication failed (invalid token, 401/403), should logout
 * - unknown_error: Other errors
 */
export const oAuthErrorCode = z.enum([
  "network_error",
  "server_error",
  "auth_error",
  "unknown_error",
]);
export type OAuthErrorCode = z.infer<typeof oAuthErrorCode>;

export const oAuthTokenResponse = z.object({
  access_token: z.string(),
  expires_in: z.number(),
  token_type: z.string(),
  scope: z.string().optional().default(""),
  refresh_token: z.string().optional(),
  scoped_organizations: z.array(z.string()).optional(),
  scoped_teams: z.array(z.number()).optional(),
});
export type OAuthTokenResponse = z.infer<typeof oAuthTokenResponse>;
export const startFlowOutput = z.object({
  success: z.boolean(),
  data: oAuthTokenResponse.optional(),
  error: z.string().optional(),
  errorCode: oAuthErrorCode.optional(),
});
export type StartFlowOutput = z.infer<typeof startFlowOutput>;
export const refreshTokenOutput = z.object({
  success: z.boolean(),
  data: oAuthTokenResponse.optional(),
  error: z.string().optional(),
  errorCode: oAuthErrorCode.optional(),
});
export type RefreshTokenOutput = z.infer<typeof refreshTokenOutput>;

export const cancelFlowOutput = z.object({
  success: z.boolean(),
  error: z.string().optional(),
});
export type CancelFlowOutput = z.infer<typeof cancelFlowOutput>;
