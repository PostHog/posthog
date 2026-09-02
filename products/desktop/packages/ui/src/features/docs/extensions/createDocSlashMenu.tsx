import {
  CodeIcon,
  ListBulletsIcon,
  ListChecksIcon,
  ListNumbersIcon,
  MinusIcon,
  QuotesIcon,
  TableIcon,
  TextHOneIcon,
  TextHThreeIcon,
  TextHTwoIcon,
} from "@phosphor-icons/react";
import { DocMark } from "@posthog/ui/primitives/DocMark";
import type { Editor, Extension } from "@tiptap/core";
import { createDocSuggestion } from "./createDocSuggestion";
import type { DocSuggestionItem } from "./DocSuggestionList";

/** What the person chose, once the typeahead has narrowed it down. */
export type DocSlashChoice =
  | { kind: "heading"; level: 1 | 2 | 3 }
  | { kind: "code" }
  | { kind: "bulletList" }
  | { kind: "orderedList" }
  | { kind: "taskList" }
  | { kind: "quote" }
  | { kind: "divider" }
  | { kind: "sql" }
  | { kind: "data" };

interface SlashItem extends DocSuggestionItem {
  choice: DocSlashChoice;
  /** Other words a person might type for it. */
  keywords?: string;
}

const ICON = 15;

/**
 * The blocks `/` offers, in the order a page uses them.
 *
 * Nothing here searches. A data point comes from asking with `+`, because a
 * person knows what they want to see long before they know which saved insight
 * holds it.
 */
const BLOCKS: SlashItem[] = [
  {
    id: "data",
    group: "Data",
    icon: <DocMark variant="agent" state="still" size={13} />,
    label: "Data point",
    description: "a live number",
    hint: "+",
    keywords: "number metric ask agent insight",
    choice: { kind: "data" },
  },
  {
    id: "sql",
    group: "Data",
    icon: <TableIcon size={ICON} />,
    label: "SQL query",
    description: "rows from a query",
    keywords: "hogql table",
    choice: { kind: "sql" },
  },
  {
    id: "heading-1",
    group: "Text",
    icon: <TextHOneIcon size={ICON} />,
    label: "Heading",
    description: "a section",
    hint: "#",
    keywords: "h1 title",
    choice: { kind: "heading", level: 1 },
  },
  {
    id: "heading-2",
    group: "Text",
    icon: <TextHTwoIcon size={ICON} />,
    label: "Subheading",
    description: "a part of a section",
    hint: "##",
    keywords: "h2",
    choice: { kind: "heading", level: 2 },
  },
  {
    id: "heading-3",
    group: "Text",
    icon: <TextHThreeIcon size={ICON} />,
    label: "Small heading",
    description: "the level under that",
    hint: "###",
    keywords: "h3",
    choice: { kind: "heading", level: 3 },
  },
  {
    id: "quote",
    group: "Text",
    icon: <QuotesIcon size={ICON} />,
    label: "Quote",
    description: "someone else's words",
    hint: ">",
    keywords: "blockquote",
    choice: { kind: "quote" },
  },
  {
    id: "code",
    group: "Text",
    icon: <CodeIcon size={ICON} />,
    label: "Code",
    description: "kept as written",
    hint: "```",
    keywords: "snippet",
    choice: { kind: "code" },
  },
  {
    id: "bullet-list",
    group: "Lists",
    icon: <ListBulletsIcon size={ICON} />,
    label: "Bullet list",
    description: "points",
    hint: "-",
    keywords: "unordered",
    choice: { kind: "bulletList" },
  },
  {
    id: "ordered-list",
    group: "Lists",
    icon: <ListNumbersIcon size={ICON} />,
    label: "Numbered list",
    description: "steps in order",
    hint: "1.",
    keywords: "ordered",
    choice: { kind: "orderedList" },
  },
  {
    id: "task-list",
    group: "Lists",
    icon: <ListChecksIcon size={ICON} />,
    label: "Task list",
    description: "checkboxes",
    hint: "[]",
    keywords: "todo checklist",
    choice: { kind: "taskList" },
  },
  {
    id: "divider",
    group: "Lists",
    icon: <MinusIcon size={ICON} />,
    label: "Divider",
    description: "a line between sections",
    hint: "---",
    keywords: "rule hr",
    choice: { kind: "divider" },
  },
];

/**
 * `/` in a doc.
 *
 * One list of blocks, filtered as you type. Nothing here opens a window.
 */
export function createDocSlashMenu(options: {
  sessionId: string;
  onPick: (choice: DocSlashChoice, editor: Editor) => void;
}): Extension {
  return createDocSuggestion<SlashItem>({
    name: "docSlashMenu",
    sessionId: options.sessionId,
    char: "/",
    startOfLine: false,
    allowSpaces: false,
    emptyMessage: "No block by that name",
    items: (query) => {
      const needle = query.trim().toLowerCase();
      if (!needle) return BLOCKS;
      return BLOCKS.filter((item) =>
        `${item.label} ${item.description ?? ""} ${item.keywords ?? ""}`
          .toLowerCase()
          .includes(needle),
      );
    },
    onSelect: ({ editor, item }) => options.onPick(item.choice, editor),
  });
}
