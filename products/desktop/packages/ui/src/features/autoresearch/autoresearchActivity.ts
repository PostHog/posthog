import { parsePlanReport } from "@posthog/core/autoresearch/prompts";
import type { AcpMessage } from "@posthog/shared";

export type AutoresearchActivityKind =
  | "research"
  | "implementation"
  | "measurement"
  | "execution"
  | "reasoning";

export interface AutoresearchActivityItem {
  id: string;
  kind: AutoresearchActivityKind;
  label: string;
  at: number;
  updatedAt: number;
  command: boolean;
  running: boolean;
  active: boolean;
}

export interface AutoresearchActivitySnapshot {
  currentPlan: ReturnType<typeof parsePlanReport>;
  items: AutoresearchActivityItem[];
  timeByKind: Record<AutoresearchActivityKind, number>;
}

export interface AutoresearchActivityOptions {
  live?: boolean;
  pauseIntervals?: Array<{ startedAt: number; endedAt: number }>;
  pausedDurationMs?: number;
}

export function analyzeAutoresearchActivity(
  events: AcpMessage[],
  startedAt: number,
  endedAt: number | null,
  now: number,
  options: AutoresearchActivityOptions = {},
): AutoresearchActivitySnapshot {
  const live = options.live ?? endedAt === null;
  const relevant = events.filter(
    (event) =>
      event.ts >= startedAt && (endedAt === null || event.ts <= endedAt),
  );
  const items = new Map<string, AutoresearchActivityItem>();
  const agentText: string[] = [];

  for (const event of relevant) {
    const message = event.message;
    if (!("method" in message) || message.method !== "session/update") continue;
    const params = message.params as
      | {
          update?: {
            sessionUpdate?: string;
            toolCallId?: string;
            title?: string;
            kind?: string | null;
            status?: string | null;
            rawInput?: Record<string, unknown>;
            content?: { type?: string; text?: string };
          };
        }
      | undefined;
    const update = params?.update;
    if (!update) continue;

    if (
      update.sessionUpdate === "agent_message_chunk" &&
      update.content?.type === "text" &&
      update.content.text
    ) {
      agentText.push(update.content.text);
      continue;
    }

    if (
      update.sessionUpdate !== "tool_call" &&
      update.sessionUpdate !== "tool_call_update"
    ) {
      continue;
    }

    const id = update.toolCallId ?? `${event.ts}:${update.title ?? "tool"}`;
    const existing = items.get(id);
    const rawCommand = update.rawInput?.command;
    const command = typeof rawCommand === "string" ? rawCommand : undefined;
    const toolKind = update.kind ?? (existing?.command ? "execute" : undefined);
    const label = command || update.title || existing?.label;
    const kind = toolKind
      ? activityKindForTool(toolKind, label)
      : existing?.kind;
    if (!kind) continue;
    let running = existing?.running ?? false;
    if (update.status !== undefined && update.status !== null) {
      running = update.status === "in_progress" || update.status === "pending";
    }
    items.set(id, {
      id,
      kind,
      label: label || activityLabel(kind),
      at: existing?.at ?? event.ts,
      updatedAt: event.ts,
      command: toolKind === "execute",
      running: live && running,
      active: false,
    });
  }

  const currentPlan = parsePlanReport(agentText.join(""));
  const end = endedAt ?? now;
  const timeline = Array.from(items.values()).sort((a, b) => a.at - b.at);
  const currentItemId = timeline.findLast((item) => item.running)?.id;
  const displayItems = [...timeline]
    .sort((left, right) => right.at - left.at)
    .slice(0, 12)
    .map((item) => ({ ...item, active: item.id === currentItemId }));
  const boundaries = timeline.map((item) => ({ at: item.at, kind: item.kind }));
  const pauseIntervals = normalizePauseIntervals(
    options.pauseIntervals ?? [],
    startedAt,
    end,
  );
  const trackedPausedDurationMs = pauseIntervals.reduce(
    (total, interval) => total + interval.endedAt - interval.startedAt,
    0,
  );
  const pausedDurationMs = Math.max(
    trackedPausedDurationMs,
    options.pausedDurationMs ?? 0,
  );
  let remainingActiveMs = Math.max(0, end - startedAt - pausedDurationMs);
  const timeByKind: Record<AutoresearchActivityKind, number> = {
    research: 0,
    implementation: 0,
    measurement: 0,
    execution: 0,
    reasoning: 0,
  };
  let cursor = startedAt;
  let kind: AutoresearchActivityKind = "reasoning";
  for (const boundary of boundaries) {
    const duration = activeDurationBetween(cursor, boundary.at, pauseIntervals);
    const observedDuration = Math.min(duration, remainingActiveMs);
    timeByKind[kind] += observedDuration;
    remainingActiveMs -= observedDuration;
    cursor = boundary.at;
    kind = boundary.kind;
  }
  const duration = activeDurationBetween(cursor, end, pauseIntervals);
  timeByKind[kind] += Math.min(duration, remainingActiveMs);

  return {
    currentPlan,
    items: displayItems,
    timeByKind,
  };
}

function normalizePauseIntervals(
  intervals: Array<{ startedAt: number; endedAt: number }>,
  startedAt: number,
  endedAt: number,
): Array<{ startedAt: number; endedAt: number }> {
  const sorted = intervals
    .map((interval) => ({
      startedAt: Math.max(startedAt, interval.startedAt),
      endedAt: Math.min(endedAt, interval.endedAt),
    }))
    .filter((interval) => interval.endedAt > interval.startedAt)
    .sort((left, right) => left.startedAt - right.startedAt);
  const merged: Array<{ startedAt: number; endedAt: number }> = [];
  for (const interval of sorted) {
    const previous = merged.at(-1);
    if (!previous || interval.startedAt > previous.endedAt) {
      merged.push(interval);
      continue;
    }
    previous.endedAt = Math.max(previous.endedAt, interval.endedAt);
  }
  return merged;
}

function activeDurationBetween(
  startedAt: number,
  endedAt: number,
  pauseIntervals: Array<{ startedAt: number; endedAt: number }>,
): number {
  const duration = Math.max(0, endedAt - startedAt);
  const pausedDuration = pauseIntervals.reduce((total, interval) => {
    const overlapStart = Math.max(startedAt, interval.startedAt);
    const overlapEnd = Math.min(endedAt, interval.endedAt);
    return total + Math.max(0, overlapEnd - overlapStart);
  }, 0);
  return Math.max(0, duration - pausedDuration);
}

function activityKindForTool(
  kind?: string | null,
  label?: string,
): AutoresearchActivityKind {
  if (kind === "edit" || kind === "delete" || kind === "move") {
    return "implementation";
  }
  if (kind === "execute") return activityKindForCommand(label);
  if (kind === "read" || kind === "search" || kind === "fetch") {
    return "research";
  }
  return "reasoning";
}

function activityKindForCommand(label?: string): AutoresearchActivityKind {
  const command = label?.toLowerCase() ?? "";
  if (/\b(apply_patch|edit|write|delete|rename)\b/.test(command)) {
    return "implementation";
  }
  if (
    /\b(bench(?:mark)?|test|vitest|jest|pytest|typecheck|type-check|tsc|lint|biome|build)\b/.test(
      command,
    )
  ) {
    return "measurement";
  }
  if (
    /\b(search|inspect|read|status|diff|log|show)\b/.test(command) ||
    /\b(rg|grep|cat|head|tail|find|ls|sed\s+-n)\b/.test(command)
  ) {
    return "research";
  }
  return "execution";
}

function activityLabel(kind: AutoresearchActivityKind): string {
  if (kind === "implementation") return "Editing code";
  if (kind === "measurement") return "Running a command";
  if (kind === "execution") return "Running a command";
  if (kind === "research") return "Inspecting the codebase";
  return "Working";
}
