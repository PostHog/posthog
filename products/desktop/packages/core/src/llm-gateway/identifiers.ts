export const LLM_GATEWAY_SERVICE = Symbol.for("posthog.core.llmGatewayService");
export const LLM_GATEWAY_HOST = Symbol.for("posthog.core.llmGatewayHost");

export interface LlmGatewayAuth {
  getValidAccessToken(): Promise<{ accessToken: string; apiHost: string }>;
  authenticatedFetch(url: string, init?: RequestInit): Promise<Response>;
}

export interface LlmGatewayEndpoints {
  messagesUrl(apiHost: string): string;
  usageUrl(apiHost: string): string;
  defaultModel: string;
}

export interface LlmGatewayHost extends LlmGatewayAuth, LlmGatewayEndpoints {}

export interface LlmGatewayLogger {
  debug(message: string, ...args: unknown[]): void;
  info(message: string, ...args: unknown[]): void;
  warn(message: string, ...args: unknown[]): void;
  error(message: string, ...args: unknown[]): void;
}
