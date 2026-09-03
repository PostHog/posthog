import type { CanvasV2LogEntry } from "@posthog/shared";
import type { FragmentLastEdit } from "./components/FragmentOverlay";

const MINUTE = 60_000;

/** Who last changed each fragment, from the log the sync client holds. */
export function buildLastEdits(
  log: readonly CanvasV2LogEntry[],
): Record<string, FragmentLastEdit> {
  const edits: Record<string, FragmentLastEdit> = {};
  for (const entry of log) {
    const id = fragmentIdOf(entry);
    if (!id) continue;
    edits[id] = {
      name: actorName(entry),
      when: relativeTime(entry.createdAt),
    };
  }
  return edits;
}

function fragmentIdOf(entry: CanvasV2LogEntry): string | null {
  const op = entry.op;
  if (op.type === "add_fragment") return op.fragment.id;
  if (
    op.type === "update_fragment" ||
    op.type === "bring_to_front" ||
    op.type === "remove_fragment"
  ) {
    return op.id;
  }
  return null;
}

function actorName(entry: CanvasV2LogEntry): string {
  if (entry.actor.kind === "agent") return "the agent";
  return entry.actor.userName ?? "someone";
}

function relativeTime(iso: string): string {
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return "recently";
  const minutes = Math.round((Date.now() - then) / MINUTE);
  if (minutes < 1) return "just now";
  if (minutes === 1) return "1 minute ago";
  if (minutes < 60) return `${minutes} minutes ago`;
  const hours = Math.round(minutes / 60);
  if (hours === 1) return "1 hour ago";
  if (hours < 24) return `${hours} hours ago`;
  const days = Math.round(hours / 24);
  return days === 1 ? "1 day ago" : `${days} days ago`;
}
