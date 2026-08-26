export type Adapter = "claude" | "codex";

/**
 * How Codex sessions authenticate for model calls: through the PostHog LLM
 * gateway (default), or on the user's own ChatGPT subscription.
 */
export type CodexModelAccess = "posthog-gateway" | "own-subscription";
