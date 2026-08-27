/**
 * Pure builders for the PostHog `_posthog/*` ext-notification params the app-server
 * adapter emits so log consumers and the renderer
 * see the same shapes. Param-only (no I/O) so each is unit-testable in isolation.
 */

import type { StopReason } from "@agentclientprotocol/sdk";
import {
  buildBreakdown,
  type ContextBreakdown,
  type ContextBreakdownBaseline,
} from "../claude/context-breakdown";

/**
 * Adapter tag on `_posthog/sdk_session`. Kept `"codex"` (not `"codex-app-server"`)
 * so resume/keying treats both Codex transports as the same agent family.
 */
const CODEX_ADAPTER = "codex" as const;

export interface SdkSessionParams {
  taskRunId: string;
  sessionId: string;
  adapter: typeof CODEX_ADAPTER;
}

/** `_posthog/sdk_session` — maps a taskRunId to the sessionId so the host can resume later. */
export function buildSdkSessionParams(
  sessionId: string,
  taskRunId: string,
): SdkSessionParams {
  return {
    taskRunId,
    sessionId,
    adapter: CODEX_ADAPTER,
  };
}

/** Per-turn token usage. `totalTokens` is derived so consumers don't re-sum. */
export interface TurnCompleteUsage {
  inputTokens: number;
  outputTokens: number;
  cachedReadTokens: number;
  cachedWriteTokens: number;
  totalTokens: number;
}

export interface TurnCompleteParams {
  sessionId: string;
  stopReason: StopReason;
  usage: TurnCompleteUsage;
}

type TurnCompleteUsageInput = {
  inputTokens?: number | null;
  outputTokens?: number | null;
  cachedReadTokens?: number | null;
  cachedWriteTokens?: number | null;
};

/**
 * `_posthog/turn_complete` — fired when a prompt turn finishes. `totalTokens` is the
 * sum of all four component counts.
 */
export function buildTurnCompleteParams(
  sessionId: string,
  stopReason: StopReason,
  usage?: TurnCompleteUsageInput | null,
): TurnCompleteParams {
  const inputTokens = usage?.inputTokens ?? 0;
  const outputTokens = usage?.outputTokens ?? 0;
  const cachedReadTokens = usage?.cachedReadTokens ?? 0;
  const cachedWriteTokens = usage?.cachedWriteTokens ?? 0;
  return {
    sessionId,
    stopReason,
    usage: {
      inputTokens,
      outputTokens,
      cachedReadTokens,
      cachedWriteTokens,
      totalTokens:
        inputTokens + outputTokens + cachedReadTokens + cachedWriteTokens,
    },
  };
}

export interface UsageBreakdownParams {
  sessionId: string;
  breakdown: ContextBreakdown;
}

/**
 * `_posthog/usage_update` (breakdown variant) — per-source context attribution.
 * Codex doesn't attribute tokens by source, so we fold the baseline estimate with
 * the live `contextUsed` via `buildBreakdown`.
 */
export function buildUsageBreakdownParams(
  sessionId: string,
  baseline: ContextBreakdownBaseline,
  contextUsed: number,
): UsageBreakdownParams {
  return {
    sessionId,
    breakdown: buildBreakdown(baseline, contextUsed),
  };
}
