import type { Usage } from "@agentclientprotocol/sdk";
import {
  type ContextBreakdownBaseline,
  emptyBaseline,
} from "../claude/context-breakdown";
import { type CodexTokenCounts, readTokenUsage } from "./token-usage";

function requestUsage(counts: CodexTokenCounts): Usage {
  const inputTokens = counts.inputTokens ?? 0;
  const outputTokens = counts.outputTokens ?? 0;
  return {
    inputTokens,
    outputTokens,
    cachedReadTokens: counts.cachedInputTokens ?? 0,
    cachedWriteTokens: 0,
    thoughtTokens: counts.reasoningOutputTokens ?? 0,
    // Codex includes cached input and reasoning output in these two counts.
    // Its totalTokens can instead be a context estimate after compaction.
    totalTokens: inputTokens + outputTokens,
  };
}

function usageDelta(current: Usage, previous: Usage): Usage | undefined {
  const inputTokens = current.inputTokens - previous.inputTokens;
  const outputTokens = current.outputTokens - previous.outputTokens;
  const cachedReadTokens =
    (current.cachedReadTokens ?? 0) - (previous.cachedReadTokens ?? 0);
  const thoughtTokens =
    (current.thoughtTokens ?? 0) - (previous.thoughtTokens ?? 0);
  // A reset starts a new counter sequence; only its latest request is new usage.
  if (Math.min(inputTokens, outputTokens, cachedReadTokens, thoughtTokens) < 0)
    return undefined;
  return {
    inputTokens,
    outputTokens,
    cachedReadTokens,
    cachedWriteTokens: 0,
    thoughtTokens,
    totalTokens: inputTokens + outputTokens,
  };
}

export function mergeUsage(
  left: Usage | undefined,
  right: Usage | undefined,
): Usage | undefined {
  if (!left) return right;
  if (!right) return left;
  return {
    inputTokens: left.inputTokens + right.inputTokens,
    outputTokens: left.outputTokens + right.outputTokens,
    cachedReadTokens:
      (left.cachedReadTokens ?? 0) + (right.cachedReadTokens ?? 0),
    cachedWriteTokens:
      (left.cachedWriteTokens ?? 0) + (right.cachedWriteTokens ?? 0),
    thoughtTokens: (left.thoughtTokens ?? 0) + (right.thoughtTokens ?? 0),
    totalTokens: left.totalTokens + right.totalTokens,
  };
}

/** The live `_posthog/usage_update` fields (context-window occupancy). */
export interface UsageUpdate {
  used: number;
  size: number | null;
  usage: {
    inputTokens?: number;
    outputTokens?: number;
    cachedReadTokens?: number;
    reasoningTokens?: number;
    totalTokens?: number;
  };
}

/**
 * Tracks spending separately from context occupancy. An ACP turn can contain many
 * model requests: cumulative counter deltas count them once, while `last` drives the gauge.
 */
export class UsageTracker {
  private baseline: ContextBreakdownBaseline = emptyBaseline();
  private turnUsage?: Usage;
  private previousTotal?: Usage;
  private contextUsed?: number;

  setBaseline(baseline: ContextBreakdownBaseline): void {
    this.baseline = baseline;
  }

  get baselineBreakdown(): ContextBreakdownBaseline {
    return this.baseline;
  }

  resetForTurn(): void {
    this.turnUsage = undefined;
    this.contextUsed = undefined;
  }

  resetForThread(): void {
    this.resetForTurn();
    this.previousTotal = undefined;
  }

  /** Adopt replayed thread totals as the delta baseline without counting them as turn usage. */
  setCumulativeBaseline(params: unknown): void {
    const total = readTokenUsage(params)?.total;
    if (total) this.previousTotal = requestUsage(total);
  }

  /** Ingest a `thread/tokenUsage/updated` payload; returns the live usage_update, or null if unusable. */
  ingest(params: unknown): UsageUpdate | null {
    const reading = readTokenUsage(params);
    if (!reading) return null;
    const { context, total, used, size } = reading;
    // Drives the per-source breakdown's "conversation" bucket on turn complete.
    this.contextUsed = used;
    const cumulative = total ? requestUsage(total) : undefined;
    // The first observed snapshot may belong to a resumed thread. Without a
    // baseline, count only its latest request, not the thread's entire history.
    const delta =
      cumulative && this.previousTotal
        ? usageDelta(cumulative, this.previousTotal)
        : undefined;
    this.turnUsage = mergeUsage(this.turnUsage, delta ?? requestUsage(context));
    this.previousTotal = cumulative;
    return {
      used,
      size: size ?? null,
      usage: {
        inputTokens: context.inputTokens,
        outputTokens: context.outputTokens,
        cachedReadTokens: context.cachedInputTokens,
        reasoningTokens: context.reasoningOutputTokens,
        totalTokens: context.totalTokens,
      },
    };
  }

  perTurnUsage(): Usage | undefined {
    return this.turnUsage ? { ...this.turnUsage } : undefined;
  }

  /** Live context occupancy (same derivation as the renderer gauge), or undefined pre-usage. */
  contextTokens(): number | undefined {
    return this.contextUsed;
  }
}
