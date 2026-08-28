export type Adapter = "claude" | "codex";

export type ModelAccess = "posthog-gateway" | "own-subscription";

/** @deprecated Use ModelAccess. */
export type CodexModelAccess = ModelAccess;
