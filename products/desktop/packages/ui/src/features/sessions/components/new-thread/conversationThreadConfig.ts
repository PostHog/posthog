import {
  ArrowsLeftRight,
  Brain,
  ChatCircle,
  FileText,
  Globe,
  type Icon,
  MagnifyingGlass,
  PencilSimple,
  PuzzlePiece,
  Robot,
  Terminal,
  Trash,
  Wrench,
} from "@phosphor-icons/react";
import type { CodeToolKind } from "@posthog/ui/features/sessions/types";
import { SUBAGENT_SPAWN_TOOL_NAMES } from "../session-update/collaborationTools";

/**
 * Single source of truth for the modernized conversation thread's tuneable
 * behavior. Everything here is meant to be edited freely — no magic numbers
 * live in the components or the grouping selector.
 */

// ---------- Collapse modes ----------

/** How aggressively completed turns collapse into a tool-call group chip. */
export type CollapseMode = "all" | "partial" | "none";

export const COLLAPSE_MODE_DEFAULT: CollapseMode = "all";

export const COLLAPSE_MODE_OPTIONS: {
  value: CollapseMode;
  label: string;
  description: string;
}[] = [
  {
    value: "all",
    label: "All collapsed",
    description: "Every turn's tool activity is collapsed into a summary chip.",
  },
  {
    value: "partial",
    label: "Collapse when finished turn",
    description:
      "The active turn streams expanded; completed turns collapse to a chip.",
  },
  {
    value: "none",
    label: "No collapsing",
    description: "Everything stays expanded.",
  },
];

// ---------- Grouping ----------

export const grouping = {
  /**
   * Tool names that create a subagent. Counted separately in the chip summary.
   */
  subagentToolNames: SUBAGENT_SPAWN_TOOL_NAMES,
  /**
   * MCP-app tool calls are excluded from collapsing so their iframes stay
   * mounted (the `keepMounted` contract). Flip to false to fold them in.
   */
  excludeMcpApps: true,
  /**
   * session_update kinds that never fold into a group — always rendered as
   * their own row regardless of collapse mode (e.g. the cloud setup / clone
   * progress card).
   */
  alwaysVisibleUpdates: new Set<string>(["progress_group"]),
  /** Max distinct tool icons shown in a collapsed chip's icon strip. */
  maxIconsInChip: 10,
} as const;

/** Per-action tallies for a collapsed group. */
export interface GroupCounts {
  execute: number;
  read: number;
  edit: number;
  delete: number;
  move: number;
  search: number;
  fetch: number;
  subagents: number;
  other: number;
  messages: number;
}

function plural(n: number, singular: string, pluralForm: string): string {
  return `${n} ${n === 1 ? singular : pluralForm}`;
}

function files(n: number): string {
  return n === 1 ? "a file" : `${n} files`;
}

/**
 * The "done" summary shown once a turn completes — verb-led and action-shaped,
 * e.g. "Ran 25 commands, read a file, edited a file". Tuneable: reorder or
 * reword segments freely.
 */
export function buildDoneLabel(counts: GroupCounts): string {
  const seg: string[] = [];
  if (counts.execute > 0)
    seg.push(`ran ${plural(counts.execute, "command", "commands")}`);
  if (counts.read > 0) seg.push(`read ${files(counts.read)}`);
  if (counts.edit > 0) seg.push(`edited ${files(counts.edit)}`);
  if (counts.delete > 0) seg.push(`deleted ${files(counts.delete)}`);
  if (counts.move > 0) seg.push(`moved ${files(counts.move)}`);
  if (counts.search > 0)
    seg.push(`ran ${plural(counts.search, "search", "searches")}`);
  if (counts.fetch > 0)
    seg.push(`fetched ${plural(counts.fetch, "page", "pages")}`);
  if (counts.subagents > 0)
    seg.push(plural(counts.subagents, "subagent", "subagents"));
  if (counts.other > 0)
    seg.push(plural(counts.other, "tool call", "tool calls"));
  if (seg.length === 0) return "Worked";
  const joined = seg.join(", ");
  return joined.charAt(0).toUpperCase() + joined.slice(1);
}

const KIND_ICONS: Partial<Record<CodeToolKind, Icon>> = {
  read: FileText,
  edit: PencilSimple,
  delete: Trash,
  move: ArrowsLeftRight,
  search: MagnifyingGlass,
  execute: Terminal,
  think: Brain,
  fetch: Globe,
  question: ChatCircle,
};

export function iconForToolKind(kind: CodeToolKind | null | undefined): Icon {
  return (kind && KIND_ICONS[kind]) || Wrench;
}

export const SUBAGENT_ICON: Icon = Robot;
export const MCP_ICON: Icon = PuzzlePiece;

/** The closed set of `GroupIconEntry.key` values a chip icon can carry. */
export type GroupIconKey =
  | "subagent"
  | "mcp"
  | `kind:${CodeToolKind}`
  | "kind:other";

/** Human-readable label for a chip icon, keyed by its `GroupIconEntry.key`. */
const ICON_KEY_LABELS: Partial<Record<GroupIconKey, string>> = {
  subagent: "Spawned a subagent",
  mcp: "Called an MCP tool",
  "kind:read": "Read files",
  "kind:edit": "Edited files",
  "kind:delete": "Deleted files",
  "kind:move": "Moved files",
  "kind:search": "Searched the codebase",
  "kind:execute": "Ran terminal commands",
  "kind:think": "Thought through the problem",
  "kind:fetch": "Fetched a web page",
  "kind:question": "Asked a question",
};

export function labelForIconKey(key: GroupIconKey): string {
  return ICON_KEY_LABELS[key] ?? "Ran other tools";
}

// ---------- Motion ----------

/**
 * Motion is scoped to the content layer only — never the virtualizer's row
 * `translateY`, which it owns. All of this collapses to instant when the user
 * prefers reduced motion (handled in the components).
 */
export const motion = {
  enabled: true,
  /** Group chip mount + the expanded↔chip swap. */
  chip: {
    initial: { opacity: 0 },
    animate: { opacity: 1 },
    transition: { duration: 0.18, ease: "easeOut" as const },
  },
} as const;
