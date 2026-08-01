import type { Usage } from "@agentclientprotocol/sdk";

/**
 * Cumulative token usage for a task run, shaped for `TaskRun.state.token_usage`
 * (snake_case, matching the backend's state conventions). `turns` counts the
 * settled turns that contributed usage, giving consumers a per-turn denominator.
 */
export type RunTokenUsage = {
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
  thought_tokens: number;
  total_tokens: number;
  turns: number;
};

/**
 * Accumulates per-turn ACP `Usage` into run-level totals. The ACP usage fields
 * are optional and nullable, so every component defaults to 0 to keep the sums
 * numeric across adapters (codex reports no cache writes, claude no thought
 * tokens on some models).
 */
export class RunUsageAccumulator {
  private totals: RunTokenUsage = {
    input_tokens: 0,
    output_tokens: 0,
    cache_read_tokens: 0,
    cache_write_tokens: 0,
    thought_tokens: 0,
    total_tokens: 0,
    turns: 0,
  };

  /** Adds a settled turn's usage. Returns false when there was nothing to add. */
  add(usage: Usage | null | undefined): boolean {
    if (!usage) return false;
    this.totals.input_tokens += usage.inputTokens ?? 0;
    this.totals.output_tokens += usage.outputTokens ?? 0;
    this.totals.cache_read_tokens += usage.cachedReadTokens ?? 0;
    this.totals.cache_write_tokens += usage.cachedWriteTokens ?? 0;
    this.totals.thought_tokens += usage.thoughtTokens ?? 0;
    this.totals.total_tokens += usage.totalTokens ?? 0;
    this.totals.turns += 1;
    return true;
  }

  snapshot(): RunTokenUsage {
    return { ...this.totals };
  }
}
