import type { Usage } from "@agentclientprotocol/sdk";
import { z } from "zod/v4";
import type { PostHogAPIClient } from "../posthog-api";
import type { Logger } from "../utils/logger";

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

  seed(totals: RunTokenUsage): boolean {
    if (this.totals.turns > 0 || this.totals.total_tokens > 0) return false;
    this.totals = { ...totals };
    return true;
  }

  snapshot(): RunTokenUsage {
    return { ...this.totals };
  }
}

const storedTokenCount = z.number().int().nonnegative().catch(0);

const storedRunTokenUsageSchema = z.object({
  input_tokens: storedTokenCount,
  output_tokens: storedTokenCount,
  cache_read_tokens: storedTokenCount,
  cache_write_tokens: storedTokenCount,
  thought_tokens: storedTokenCount,
  total_tokens: storedTokenCount,
  turns: storedTokenCount,
});

export function seedRunUsage(
  accumulator: RunUsageAccumulator,
  storedTokenUsage: unknown,
): boolean {
  const parsed = storedRunTokenUsageSchema.safeParse(storedTokenUsage);
  if (!parsed.success) return false;
  return accumulator.seed(parsed.data);
}

const inflightReports = new WeakMap<RunUsageAccumulator, Promise<void>>();

export function reportRunUsage(
  accumulator: RunUsageAccumulator,
  api: PostHogAPIClient,
  taskId: string,
  runId: string,
  logger: Logger,
): Promise<void> {
  const send = (): Promise<void> =>
    api
      .updateTaskRun(taskId, runId, {
        state: { token_usage: accumulator.snapshot() },
      })
      .then(
        () => undefined,
        (error: unknown) => {
          logger.warn("Failed to report run token usage", error);
        },
      );
  const previous = inflightReports.get(accumulator);
  const next = previous ? previous.then(send) : send();
  inflightReports.set(accumulator, next);
  void next.then(() => {
    if (inflightReports.get(accumulator) === next) {
      inflightReports.delete(accumulator);
    }
  });
  return next;
}
