import { extractUserPromptsFromEvents } from "@posthog/core/sessions/sessionEvents";
import type { AcpMessage } from "@posthog/shared";

interface PromptCountEntry {
  first: AcpMessage | undefined;
  last: AcpMessage | undefined;
  scanned: number;
  count: number;
}

const MAX_ENTRIES = 64;
const entries = new Map<string, PromptCountEntry>();

function extendsScanned(
  entry: PromptCountEntry,
  events: AcpMessage[],
): boolean {
  if (events.length < entry.scanned) return false;
  if (entry.scanned === 0) return true;
  return events[0] === entry.first && events[entry.scanned - 1] === entry.last;
}

export function countUserPrompts(
  taskRunId: string,
  events: AcpMessage[],
): number {
  const entry = entries.get(taskRunId);
  if (entry && extendsScanned(entry, events)) {
    if (events.length > entry.scanned) {
      entry.count += extractUserPromptsFromEvents(
        events.slice(entry.scanned),
      ).length;
      entry.scanned = events.length;
      entry.last = events[events.length - 1];
    }
    return entry.count;
  }
  const fresh: PromptCountEntry = {
    first: events[0],
    last: events[events.length - 1],
    scanned: events.length,
    count: extractUserPromptsFromEvents(events).length,
  };
  entries.delete(taskRunId);
  entries.set(taskRunId, fresh);
  if (entries.size > MAX_ENTRIES) {
    const oldest = entries.keys().next().value;
    if (oldest !== undefined) entries.delete(oldest);
  }
  return fresh.count;
}

export function resetPromptCountsForTests(): void {
  entries.clear();
}
