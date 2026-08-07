import type { Usage } from "@agentclientprotocol/sdk";
import {
  type ContextBreakdownBaseline,
  emptyBaseline,
} from "../claude/context-breakdown";
import { readTokenUsage } from "./token-usage";

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
  private contextUsed?: number;

  setBaseline(baseline: ContextBreakdownBaseline): void {
    this.baseline = baseline;
  }

  get baselineBreakdown(): ContextBreakdownBaseline {
    return this.baseline;
  }

  resetForTurn(): void {
    this.lastTurn = undefined;
    this.contextUsed = undefined;
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
    return this.lastTurn ? { ...this.lastTurn } : undefined;
  }

  /** Live context occupancy (same derivation as the renderer gauge), or undefined pre-usage. */
  contextTokens(): number | undefined {
    return this.contextUsed;
  }
}
