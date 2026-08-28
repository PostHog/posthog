/** One turn's counts from codex's `thread/tokenUsage/updated`. */
export interface CodexTokenCounts {
  inputTokens?: number;
  cachedInputTokens?: number;
  outputTokens?: number;
  reasoningOutputTokens?: number;
  totalTokens?: number;
}

interface CodexTokenUsagePayload {
  tokenUsage?: {
    total?: CodexTokenCounts;
    last?: CodexTokenCounts;
    modelContextWindow?: number;
  };
}

export interface TokenUsageReading {
  /** This turn's counts: `last`, falling back to cumulative `total` for pre-`last` builds. */
  context: CodexTokenCounts;
  /** Context-window occupancy: `totalTokens`, falling back to `inputTokens`. */
  used: number;
  /** The model context window, when the protocol reports it. */
  size: number | undefined;
}

/**
 * The one place a `thread/tokenUsage/updated` payload is decoded, so the
 * renderer gauge (mapping.ts) and the usage breakdown (usage-tracker.ts)
 * cannot drift onto different fallback orders.
 */
export function readTokenUsage(params: unknown): TokenUsageReading | null {
  const tu = (params as CodexTokenUsagePayload | undefined)?.tokenUsage;
  // This turn's `last`, not cumulative `total` (which over-reports and pegs the
  // gauge); `total` is the fallback for pre-`last` builds.
  const context = tu?.last ?? tu?.total;
  if (!context) return null;
  const used = context.totalTokens ?? context.inputTokens;
  if (used == null) return null;
  return { context, used, size: tu?.modelContextWindow ?? undefined };
}
