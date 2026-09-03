export type Adapter = "claude" | "codex";

export type ModelAccess = "posthog-gateway" | "own-subscription";

/**
 * Pi's own native OAuth providers for bring-your-own-subscription, distinct
 * from the ACP adapters above: these are pi-ai's built-in provider ids, used
 * only by the in-process Pi harness, not the "posthog" gateway provider.
 */
export type PiSubscriptionProvider = "anthropic" | "openai-codex";

export type PiSubscriptionLoginState = "logged-in" | "logged-out" | "unknown";

/**
 * The user's persisted billing preference for Pi sessions — mirrors
 * `ModelAccess` above, but three-way since Pi's own subscription is one of
 * two distinct providers rather than a single "own-subscription" choice.
 * Defaults to "posthog-gateway": same as Claude/Codex, being logged in
 * does not by itself switch billing.
 */
export type PiModelAccess = "posthog-gateway" | PiSubscriptionProvider;

/** Model to run with when a Pi session uses the user's own subscription. */
export const PI_SUBSCRIPTION_DEFAULT_MODEL_ID: Record<
  PiSubscriptionProvider,
  string
> = {
  anthropic: "claude-sonnet-4-5",
  "openai-codex": "gpt-5.6-terra",
};
