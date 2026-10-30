import { decodeKittyPrintable, matchesKey } from "@earendil-works/pi-tui";
import { formatRelativeAge, type Task } from "@posthog/shared";
import { isTyping, PASTE_START } from "./composer";
import {
  activityOf,
  chatIndicator,
  type Indicator,
  type LocalChatState,
} from "./sidebar";

const PASTE_END = "\u001b[201~";

export interface SearchRow {
  taskId: string;
  title: string;
  indicator: Indicator | null;
  // Runs on this machine rather than in the cloud.
  local: boolean;
  // When something last happened in the chat, or empty when nothing says.
  age: string;
}

export function searchRows(
  tasks: Task[],
  {
    working,
    waiting,
    local,
  }: { working: Set<string>; waiting: Set<string>; local: LocalChatState },
): SearchRow[] {
  return tasks.map((task) => {
    const runsHere = local.active.has(task.id);
    const activity = activityOf(task, local);
    return {
      taskId: task.id,
      title: task.title || "Untitled",
      indicator: chatIndicator(task.id, task, runsHere, {
        working,
        waiting,
        running: local.running,
      }),
      local: runsHere,
      age: activity ? formatRelativeAge(activity) : "",
    };
  });
}

// The query after a key: typed or pasted text joins the end, and Backspace takes the last character.
export function editQuery(query: string, sequence: string): string {
  if (matchesKey(sequence, "backspace")) return query.slice(0, -1);
  if (!isTyping(sequence)) return query;
  if (sequence.startsWith(PASTE_START)) {
    const pasted = sequence.replace(PASTE_START, "").replace(PASTE_END, "");
    return query + pasted.replace(/\s+/g, " ");
  }
  return query + (decodeKittyPrintable(sequence) ?? sequence);
}
