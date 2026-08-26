export type Adapter = "claude" | "codex";

/** How Codex sessions pay for model calls: the gateway (default) or the user's ChatGPT subscription. */
export type CodexModelAccess = "posthog-gateway" | "own-subscription";
