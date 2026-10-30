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

// Whether the agent is compacting its context. A request to compact can give up first, so this reads the chat's events.
export function isCompacting(entries: StoredLogEntry[]): boolean {
  for (let index = entries.length - 1; index >= 0; index--) {
    const event = entries[index].type === "pi_event" && entries[index].event;
    if (!event || event.type !== "runtime_status") continue;
    if (event.status === "compacting_failed") return false;
    if (event.status === "compacting") return event.isComplete !== true;
  }
  return false;
}

// Claude Code reports its context as an ACP usage update; the window can be unknown, which leaves the fill unknown.
function acpUsage(entry: StoredLogEntry): ContextFill | null | undefined {
  const notification = entry.notification;
  if (notification?.method !== "session/update") return undefined;
  const update = (
    notification.params as
      | { update?: { sessionUpdate?: string; used?: number; size?: number } }
      | undefined
  )?.update;
  if (update?.sessionUpdate !== "usage_update") return undefined;
  if (typeof update.used !== "number" || !update.size) return null;
  return { tokens: update.used, window: update.size };
}

// How full the agent's context was after its last turn, the way the desktop reads it from turn usage.
// A compaction since then leaves the size unknown until the next turn reports it.
export function contextFill(entries: StoredLogEntry[]): ContextFill | null {
  let tokens: number | null = null;
  for (let index = entries.length - 1; index >= 0; index--) {
    const acp = acpUsage(entries[index]);
    if (acp !== undefined) return acp;
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

// The composer's corner: the context donut, then the task's cost so far ($0.00 until spend is attributed), or the user's own plan that pays instead.
// Background shells come first, as the agent's own status line names them, such as "2 shells · 1 monitor".
export function usageStatus(
  fill: ContextFill | null,
  costUsd: number | { plan: string } | null,
  shells?: string,
): string {
  const cost =
    typeof costUsd === "object" && costUsd !== null
      ? costUsd.plan
      : formatCostUsd(costUsd ?? 0);
  // The cost is faint like the rule it sits on; only the donut's colour should catch the eye.
  const faint = `\u001b[2m${fill ? " • " : ""}${cost}\u001b[22m`;
  const usage = `${fill ? donut(fill) : ""}${faint}`;
  if (!shells) return usage;
  return `\u001b[2m${shells}${usage ? " • " : ""}\u001b[22m${usage}`;
}

// 150000 reads "150k", and 1240000 "1.2M".
export function tokenCount(tokens: number): string {
  if (tokens >= 999_500)
    return `${(tokens / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
  return tokens >= 1000 ? `${Math.round(tokens / 1000)}k` : String(tokens);
}

// The status line the agent's background shells extension last set, from the run's extension events.
export const SHELLS_STATUS_KEY = "background-shells";

export function shellsStatus(entries: StoredLogEntry[]): string | undefined {
  for (let index = entries.length - 1; index >= 0; index--) {
    const entry = entries[index];
    if (entry.type !== "pi_extension_event") continue;
    const params = (entry as { notification?: { params?: unknown } })
      .notification?.params as
      | { method?: string; statusKey?: string; statusText?: string }
      | undefined;
    if (
      params?.method !== "setStatus" ||
      params.statusKey !== SHELLS_STATUS_KEY
    )
      continue;
    return params.statusText || undefined;
  }
  return undefined;
}
