export type Adapter = "claude" | "codex";

export type ModelAccess = "posthog-gateway" | "own-subscription";

export type PiSubscriptionProvider = "anthropic" | "openai-codex";

export type PiSubscriptionLoginState = "logged-in" | "logged-out" | "unknown";

export type PiModelAccess = "posthog-gateway" | PiSubscriptionProvider;

export const PI_SUBSCRIPTION_DEFAULT_MODEL_ID: Record<
  PiSubscriptionProvider,
  string
> = {
  anthropic: "claude-sonnet-4-5",
  "openai-codex": "gpt-5.6-terra",
};
