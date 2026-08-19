import type { Usage } from "@agentclientprotocol/sdk";
import {
  type ContextBreakdownBaseline,
  emptyBaseline,
} from "../claude/context-breakdown";
import { readTokenUsage } from "./token-usage";

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
 * Tracks token usage for one codex thread. codex's `thread/tokenUsage/updated` carries
 * `{ total, last, modelContextWindow }`; `last` drives both context occupancy and per-turn
 * usage rather than diffing `total` (a fallback for builds predating `last`).
 */
export class UsageTracker {
  private baseline: ContextBreakdownBaseline = emptyBaseline();
  private lastTurn?: Usage;
  private carried?: Usage;
  private contextUsed?: number;

  setBaseline(baseline: ContextBreakdownBaseline): void {
    this.baseline = baseline;
  }

  get baselineBreakdown(): ContextBreakdownBaseline {
    return this.baseline;
  }

  resetForTurn(): void {
    this.lastTurn = undefined;
    this.carried = undefined;
    this.contextUsed = undefined;
  }

  carryForNativeTurn(): void {
    this.carried = mergeUsage(this.carried, this.lastTurn);
    this.lastTurn = undefined;
  }

  /** Ingest a `thread/tokenUsage/updated` payload; returns the live usage_update, or null if unusable. */
  ingest(params: unknown): UsageUpdate | null {
    const reading = readTokenUsage(params);
    if (!reading) return null;
    const { context, used, size } = reading;
    // Drives the per-source breakdown's "conversation" bucket on turn complete.
    this.contextUsed = used;
    const inputTokens = context.inputTokens ?? 0;
    const outputTokens = context.outputTokens ?? 0;
    const cachedReadTokens = context.cachedInputTokens ?? 0;
    this.lastTurn = {
      inputTokens,
      outputTokens,
      cachedReadTokens,
      cachedWriteTokens: 0,
      thoughtTokens: context.reasoningOutputTokens,
      totalTokens:
        context.totalTokens ?? inputTokens + outputTokens + cachedReadTokens,
    };
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
    const merged = mergeUsage(this.carried, this.lastTurn);
    return merged ? { ...merged } : undefined;
  }

  /** Live context occupancy (same derivation as the renderer gauge), or undefined pre-usage. */
  contextTokens(): number | undefined {
    return this.contextUsed;
  }
}
