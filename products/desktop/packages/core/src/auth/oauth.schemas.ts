import { z } from "zod";

export const cloudRegion = z.enum(["us", "eu", "dev"]);
export type CloudRegion = z.infer<typeof cloudRegion>;

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
  refresh_token: z.string(),
  scoped_organizations: z.array(z.string()).optional(),
});
export type OAuthTokenResponse = z.infer<typeof oAuthTokenResponse>;

export const startFlowInput = z.object({
  region: cloudRegion,
});
export type StartFlowInput = z.infer<typeof startFlowInput>;

export const startFlowOutput = z.object({
  success: z.boolean(),
  data: oAuthTokenResponse.optional(),
  error: z.string().optional(),
  errorCode: oAuthErrorCode.optional(),
});
export type StartFlowOutput = z.infer<typeof startFlowOutput>;

export const startSignupFlowInput = startFlowInput;
export type StartSignupFlowInput = z.infer<typeof startSignupFlowInput>;

export const refreshTokenInput = z.object({
  refreshToken: z.string(),
  region: cloudRegion,
});
export type RefreshTokenInput = z.infer<typeof refreshTokenInput>;

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

export const openExternalUrlInput = z.object({
  url: z.string().url(),
});
export type OpenExternalUrlInput = z.infer<typeof openExternalUrlInput>;
