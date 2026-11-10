export const LLM_GATEWAY_SERVICE = Symbol.for("posthog.core.llmGatewayService");
export const LLM_GATEWAY_HOST = Symbol.for("posthog.core.llmGatewayHost");
export const GATEWAY_TOKEN_SERVICE = Symbol.for(
  "posthog.core.gatewayTokenService",
);
export const GATEWAY_TOKEN_HOST = Symbol.for("posthog.core.gatewayTokenHost");

export interface LlmGatewayAuth {
  getValidAccessToken(): Promise<{ accessToken: string; apiHost: string }>;
  authenticatedFetch(url: string, init?: RequestInit): Promise<Response>;
  /** Unauthenticated fetch for Go gateway calls, which carry their own bearer. */
  fetch?(url: string, init?: RequestInit): Promise<Response>;
}

export interface LlmGatewayEndpoints {
  messagesUrl(apiHost: string): string;
  usageUrl(apiHost: string, projectId: number): string;
  legacyUsageUrl(apiHost: string): string;
  defaultModel: string;
}

export interface LlmGatewayHost extends LlmGatewayAuth, LlmGatewayEndpoints {}

export interface LlmGatewayLogger {
  debug(message: string, ...args: unknown[]): void;
  info(message: string, ...args: unknown[]): void;
  warn(message: string, ...args: unknown[]): void;
  error(message: string, ...args: unknown[]): void;
}

export interface GatewayTokenOverride {
  url: string;
  token: string;
}

export interface GatewayTokenHost {
  /** False on hosts that cannot reach the Go gateway (the web host has no CORS path). */
  goEnabled: boolean;
  override: GatewayTokenOverride | null;
}
