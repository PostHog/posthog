export type Adapter = "claude" | "codex";

/** Whether a harness session bills model calls to PostHog credits or the user's own provider subscription. */
export type ModelAccess = "posthog-gateway" | "own-subscription";

/** @deprecated Use {@link ModelAccess} — both adapters share the vocabulary. */
export type CodexModelAccess = ModelAccess;
