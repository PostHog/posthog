import type { AgentConversationEvent, StoredLogEntry } from "@posthog/shared";
import { formatCostUsd } from "@posthog/ui/features/sessions/contextColors";
import { orange } from "./theme";

export interface ContextFill {
  tokens: number;
  window: number;
}

const isCompletedCompaction = (event: AgentConversationEvent): boolean =>
  event.type === "runtime_status" &&
  event.status === "compacting" &&
  event.isComplete === true;

// How full the agent's context was after its last turn, the way the desktop reads it from turn usage.
// A compaction since then leaves the size unknown until the next turn reports it.
export function contextFill(entries: StoredLogEntry[]): ContextFill | null {
  let tokens: number | null = null;
  for (let index = entries.length - 1; index >= 0; index--) {
    const event = entries[index].type === "pi_event" && entries[index].event;
    if (!event) continue;
    if (tokens === null && isCompletedCompaction(event)) return null;
    if (event.type !== "turn_completed" || !event.usage) continue;
    if (tokens === null) {
      tokens = event.usage.contextTokens ?? null;
      if (tokens === null) return null;
    }
    // A turn can omit the window; an older turn's still holds.
    if (event.usage.contextWindow)
      return { tokens, window: event.usage.contextWindow };
  }
  return null;
}

const DONUT = ["○", "◔", "◑", "◕", "●"];

// Colored at the desktop's thresholds, so a nearly full context stands out.
function tint(percent: number, text: string): string {
  if (percent >= 90) return `\u001b[31m${text}\u001b[39m`;
  if (percent >= 75) return orange(text);
  if (percent >= 50) return `\u001b[33m${text}\u001b[39m`;
  return `\u001b[32m${text}\u001b[39m`;
}

export function donut(fill: ContextFill): string {
  const percent = Math.min(100, (fill.tokens / fill.window) * 100);
  return tint(percent, DONUT[Math.round(percent / 25)]);
}

// The composer's corner: the context donut, then the task's cost so far.
// A zero cost is usually spend not attributed yet, so it stays hidden like an unknown one.
export function usageStatus(
  fill: ContextFill | null,
  costUsd: number | null,
): string {
  const parts = [
    ...(fill ? [donut(fill)] : []),
    ...(costUsd !== null && costUsd > 0 ? [formatCostUsd(costUsd)] : []),
  ];
  return parts.join(" • ");
}
