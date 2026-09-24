export type Adapter = "claude" | "codex";

export type ModelAccess = "posthog-gateway" | "own-subscription";

export const PI_SUBSCRIPTION_PROVIDER = "openai-codex";

export type PiSubscriptionProvider = typeof PI_SUBSCRIPTION_PROVIDER;

export type PiSubscriptionLoginState = "logged-in" | "logged-out" | "unknown";

export type PiModelAccess = "posthog-gateway" | PiSubscriptionProvider;

export const PI_SUBSCRIPTION_DEFAULT_MODEL_ID = "gpt-5.6-terra";
