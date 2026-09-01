import type { SuggestionItem } from "@posthog/ui/features/message-editor/types";
import type { Editor, Extension } from "@tiptap/core";
import { createDocSuggestion } from "./createDocSuggestion";

/** What the person chose, once the typeahead has narrowed it down. */
export type DocSlashChoice =
  | { kind: "taskList" }
  | { kind: "discussion" }
  | { kind: "sql" }
  | { kind: "insight"; shortId: string; label: string }
  | { kind: "metric"; shortId: string; label: string }
  | { kind: "task"; taskId: string; label: string };

interface SlashItem extends SuggestionItem {
  choice: DocSlashChoice;
}

/**
 * The words that switch the list from blocks to things.
 *
 * Typing `/insight weekly` searches insights straight in the popup, so adding a
 * chart never leaves the page. Each entry says which source the rest of the
 * query searches.
 */
const SOURCES: Array<{
  word: string;
  label: string;
  hint: string;
  source: "insight" | "metric" | "task";
}> = [
  { word: "insight", label: "Insight", hint: "chart", source: "insight" },
  {
    word: "number",
    label: "Number",
    hint: "one value in a row",
    source: "metric",
  },
  { word: "task", label: "Task", hint: "link one that exists", source: "task" },
];

const BLOCKS: SlashItem[] = [
  {
    id: "sql",
    label: "SQL query",
    description: "rows",
    choice: { kind: "sql" },
  },
  {
    id: "task-list",
    label: "Task list",
    description: "checkboxes",
    choice: { kind: "taskList" },
  },
  {
    id: "discussion",
    label: "Discussion",
    description: "on the selected text",
    choice: { kind: "discussion" },
  },
];

export interface DocSlashSources {
  /** Saved insights matching a search. */
  insights: (
    query: string,
  ) => Promise<Array<{ shortId: string; label: string }>>;
  /** Tasks in this space matching a search. */
  tasks: (query: string) => Array<{ taskId: string; label: string }>;
}

function splitQuery(query: string): { word: string; rest: string } {
  const trimmed = query.trimStart();
  const space = trimmed.indexOf(" ");
  if (space < 0) return { word: trimmed.toLowerCase(), rest: "" };
  return {
    word: trimmed.slice(0, space).toLowerCase(),
    rest: trimmed.slice(space + 1).trim(),
  };
}

/**
 * `/` in a doc.
 *
 * One popup does everything: the plain list of blocks, and a search over the
 * real thing as soon as the query names a source. Nothing here opens a window.
 */
export function createDocSlashMenu(options: {
  sessionId: string;
  sources: DocSlashSources;
  onPick: (choice: DocSlashChoice, editor: Editor) => void;
}): Extension {
  return createDocSuggestion<SlashItem>({
    name: "docSlashMenu",
    sessionId: options.sessionId,
    char: "/",
    startOfLine: true,
    allowSpaces: true,
    debounceMs: 150,
    items: async (query) => {
      const { word, rest } = splitQuery(query);
      const matched = SOURCES.find(
        (source) => word.length >= 2 && source.word.startsWith(word),
      );

      if (matched?.source === "task") {
        return options.sources.tasks(rest).map((task) => ({
          id: task.taskId,
          label: task.label,
          description: "task in this space",
          choice: { kind: "task", taskId: task.taskId, label: task.label },
        }));
      }

      if (matched) {
        const insights = await options.sources.insights(rest);
        return insights.map((insight) => ({
          id: insight.shortId,
          label: insight.label,
          description:
            matched.source === "metric" ? "as a number" : "as a chart",
          choice: {
            kind: matched.source === "metric" ? "metric" : "insight",
            shortId: insight.shortId,
            label: insight.label,
          },
        }));
      }

      // No source named yet: offer the blocks, plus the sources as words to type.
      const needle = word;
      const sourceItems: SlashItem[] = SOURCES.map((source) => ({
        id: `source-${source.word}`,
        label: source.label,
        description: `${source.hint} — keep typing to search`,
        // Selecting a source word only moves the query along; the real choice
        // comes from the search that follows.
        choice: { kind: "taskList" },
      }));
      const all = [...sourceItems, ...BLOCKS];
      return needle
        ? all.filter((item) => item.label.toLowerCase().includes(needle))
        : all;
    },
    renderItem: undefined,
    onSelect: ({ editor, item }) => {
      if (item.id.startsWith("source-")) {
        const word = item.id.slice("source-".length);
        editor.chain().focus().insertContent(`/${word} `).run();
        return;
      }
      options.onPick(item.choice, editor);
    },
  });
}
