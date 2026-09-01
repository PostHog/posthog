import type { SuggestionItem } from "@posthog/ui/features/message-editor/types";
import type { Editor, Extension } from "@tiptap/core";
import { createDocSuggestion } from "./createDocSuggestion";

export type DocBlockKind =
  | "sql"
  | "insight"
  | "metricRow"
  | "taskList"
  | "task"
  | "discussion";

/** What each `/` entry is called and what it says it does. */
const SLASH_ITEMS: Array<SuggestionItem & { kind: DocBlockKind }> = [
  { id: "sql", label: "SQL query", description: "rows", kind: "sql" },
  { id: "insight", label: "Insight", description: "chart", kind: "insight" },
  {
    id: "metric-row",
    label: "Metric row",
    description: "numbers",
    kind: "metricRow",
  },
  {
    id: "task-list",
    label: "Task list",
    description: "checkboxes",
    kind: "taskList",
  },
  { id: "task", label: "Task", description: "inline", kind: "task" },
  {
    id: "discussion",
    label: "Discussion",
    description: "on the selected text",
    kind: "discussion",
  },
];

/**
 * `/` in a doc: inserts a block.
 *
 * Everything that needs a target (a chart, a task) hands off to the editor's
 * pickers rather than guessing, so the node lands with a real reference in it.
 */
export function createDocSlashMenu(options: {
  sessionId: string;
  onPick: (kind: DocBlockKind, editor: Editor) => void;
}): Extension {
  return createDocSuggestion<SuggestionItem & { kind: DocBlockKind }>({
    name: "docSlashMenu",
    sessionId: options.sessionId,
    char: "/",
    startOfLine: true,
    items: (query) => {
      const needle = query.trim().toLowerCase();
      return SLASH_ITEMS.filter(
        (item) => !needle || item.label.toLowerCase().includes(needle),
      );
    },
    onSelect: ({ editor, item }) => options.onPick(item.kind, editor),
  });
}
