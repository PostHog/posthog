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

const GATEWAY_REPORT_DEADLINE_MS = 5_000;
const GATEWAY_REPORT_RETRY_DELAYS_MS = [0, 100, 250];

function gatewayReportDelay(
  milliseconds: number,
  signal?: AbortSignal,
): Promise<void> {
  if (signal?.aborted) return Promise.resolve();
  return new Promise((resolve) => {
    const finish = (): void => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    };
    const onAbort = (): void => {
      clearTimeout(timer);
      finish();
    };
    const timer = setTimeout(finish, milliseconds);
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

export class GatewayUsageReporter {
  private readonly pendingRequestIds = new Set<string>();
  private reportChain: Promise<void> = Promise.resolve();

  constructor(
    private readonly api: PostHogAPIClient,
    private readonly taskId: string,
    private readonly runId: string,
    private readonly logger: Logger,
  ) {}

  reportRequestId(requestId: string): void {
    this.pendingRequestIds.add(requestId);
    this.reportChain = this.reportChain.then(() => this.flushRequestIds());
  }

  async stop(): Promise<void> {
    const controller = new AbortController();
    const timer = setTimeout(
      () => controller.abort(),
      GATEWAY_REPORT_DEADLINE_MS,
    );
    try {
      await Promise.race([
        this.reportChain,
        gatewayReportDelay(GATEWAY_REPORT_DEADLINE_MS, controller.signal),
      ]);
      if (!controller.signal.aborted && this.pendingRequestIds.size > 0)
        await this.flushRequestIds(controller.signal);
    } finally {
      clearTimeout(timer);
    }
  }

  private updateRun(
    payload: Parameters<PostHogAPIClient["updateTaskRun"]>[2],
    signal?: AbortSignal,
  ): Promise<unknown> {
    return this.api.updateTaskRun(
      this.taskId,
      this.runId,
      payload,
      signal ?? AbortSignal.timeout(GATEWAY_REPORT_DEADLINE_MS),
    );
  }

  private async flushRequestIds(signal?: AbortSignal): Promise<void> {
    for (const requestId of [...this.pendingRequestIds]) {
      let reported = false;
      for (const retryDelay of GATEWAY_REPORT_RETRY_DELAYS_MS) {
        if (retryDelay) await gatewayReportDelay(retryDelay, signal);
        if (signal?.aborted) return;
        try {
          await this.updateRun(
            { state_append: { unprocessed_request_ids: requestId } },
            signal
              ? AbortSignal.any([
                  signal,
                  AbortSignal.timeout(GATEWAY_REPORT_DEADLINE_MS),
                ])
              : AbortSignal.timeout(GATEWAY_REPORT_DEADLINE_MS),
          );
          reported = true;
          break;
        } catch (error) {
          if (signal?.aborted) return;
          this.logger.warn("Failed to report gateway request ID", error);
        }
      }
      if (reported) this.pendingRequestIds.delete(requestId);
    }
  }
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
