import type { Icon } from "@phosphor-icons/react";
import { readAgentToolName, readMcpToolDescriptor } from "@posthog/shared";
import type { ConversationItem } from "@posthog/ui/features/sessions/components/buildConversationItems";
import { isUserInitiatedConversationItem } from "@posthog/ui/features/sessions/components/isUserInitiatedConversationItem";
import {
  buildDoneLabel,
  type GroupCounts,
  type GroupIconKey,
  grouping,
  iconForToolKind,
  MCP_ICON,
  SUBAGENT_ICON,
} from "@posthog/ui/features/sessions/components/new-thread/conversationThreadConfig";
import { isPlanApprovalTool } from "@posthog/ui/features/sessions/components/session-update/collaborationTools";
import { hasInlineArtifact } from "@posthog/ui/features/sessions/components/session-update/inlineArtifacts";
import type { ToolCall } from "@posthog/ui/features/sessions/types";

export interface GroupIconEntry {
  Icon: Icon;
  key: GroupIconKey;
}

export interface GroupSummary {
  counts: GroupCounts;
  icons: GroupIconEntry[];
  /** Title of the most recent tool — "what's happening now" while running. */
  liveLabel: string | null;
  /** Verb-led summary shown once the turn completes. */
  doneLabel: string;
  /**
   * This group's last tool call is still pending/in_progress. A turn can span
   * several groups (messages/plans split it), so spin on the group's own work,
   * not the turn — otherwise finished earlier groups keep spinning until the
   * whole turn ends.
   */
  active: boolean;
  /**
   * The group did some countable tool work (i.e. doneLabel is a real summary,
   * not the "Worked" fallback). Lets the chip decide whether to show the
   * summary without depending on the fallback string.
   */
  hasCountableWork: boolean;
}

/**
 * One rendered row of the new thread. Either a passthrough conversation item or
 * a collapsed tool-call group standing in for a run of work items.
 */
export type ThreadRow =
  | {
      kind: "item";
      id: string;
      item: ConversationItem;
    }
  | {
      kind: "tool_group";
      id: string;
      items: ConversationItem[];
      summary: GroupSummary;
      turnComplete: boolean;
      expanded: boolean;
    };

export interface ThreadGrouping {
  rows: ThreadRow[];
  /** Row indices of standalone MCP-app items, for the list's keepMounted. */
  keepMounted: number[];
  /** Every item id (incl. those folded into a group) → its row index. */
  idToRowIndex: Map<string, number>;
}

function getToolName(update: { _meta?: unknown }): string | undefined {
  return readAgentToolName(update._meta);
}

function isMcpToolItem(item: ConversationItem): boolean {
  if (item.type !== "session_update") return false;
  if (item.update.sessionUpdate !== "tool_call") return false;
  return readMcpToolDescriptor(item.update._meta) !== undefined;
}

function isAlwaysVisibleItem(item: ConversationItem): boolean {
  return (
    item.type === "session_update" &&
    grouping.alwaysVisibleUpdates.has(item.update.sessionUpdate)
  );
}

/**
 * The agent's direct text to the user. Never folded — it surfaces as its own
 * chat row so a collapsed turn never swallows something said to the user.
 */
function isDirectMessageItem(item: ConversationItem): boolean {
  return (
    item.type === "session_update" &&
    item.update.sessionUpdate === "agent_message_chunk"
  );
}

/**
 * A plan presented for approval (the ExitPlanMode / switch_mode tool call,
 * rendered by PlanApprovalView). Keep it visible so the user can read it.
 */
export function isPlanItem(item: ConversationItem): boolean {
  return (
    item.type === "session_update" &&
    item.update.sessionUpdate === "tool_call" &&
    (item.update.kind === "switch_mode" ||
      isPlanApprovalTool(readAgentToolName(item.update._meta)))
  );
}

/**
 * A tool call that hands the user a deliverable (an uploaded file, a pull
 * request it just opened). The card belongs in the thread, so the run that
 * produced it must not fold away behind a "ran 12 commands" summary.
 */
function isArtifactItem(item: ConversationItem): boolean {
  if (item.type !== "session_update") return false;
  if (item.update.sessionUpdate !== "tool_call") return false;
  const { toolCallId } = item.update;
  // The output a PR is read from arrives on the tool_call_update, which lands
  // in the turn's map rather than on the item this grouping walks.
  const resolved = toolCallId
    ? item.turnContext.toolCalls.get(toolCallId)
    : undefined;
  return hasInlineArtifact(resolved ?? (item.update as unknown as ToolCall));
}

/**
 * Whether an item folds into a tool-call group rather than getting its own row.
 * A group is a maximal run of these; anything else flushes the run. Grouping is
 * keyed on item type alone, never on turn boundaries — a run can straddle the
 * end of one turn and the start of the next.
 */
export function isGroupableItem(item: ConversationItem): boolean {
  if (item.type !== "session_update") return false;
  if (grouping.excludeMcpApps && isMcpToolItem(item)) return false;
  if (
    isAlwaysVisibleItem(item) ||
    isDirectMessageItem(item) ||
    isPlanItem(item) ||
    isArtifactItem(item)
  )
    return false;
  return true;
}

/**
 * Tallies, icons, and live/done labels for a run of grouped items. Exported so the thread's
 * `ToolGroup` reads the same counts, keeping one definition of what "ran 3 commands" means.
 */
export function summarize(items: ConversationItem[]): GroupSummary {
  const counts: GroupCounts = {
    execute: 0,
    read: 0,
    edit: 0,
    delete: 0,
    move: 0,
    search: 0,
    fetch: 0,
    subagents: 0,
    other: 0,
    messages: 0,
  };
  let liveLabel: string | null = null;
  let lastToolStatus: string | undefined;
  let trailingThoughtStreaming = false;
  const icons: GroupIconEntry[] = [];
  const seenIcons = new Set<string>();

  const addIcon = (Icon: Icon, key: GroupIconKey) => {
    if (seenIcons.has(key) || icons.length >= grouping.maxIconsInChip) return;
    seenIcons.add(key);
    icons.push({ Icon, key });
  };

  for (const item of items) {
    if (item.type !== "session_update") continue;
    const update = item.update;
    if (update.sessionUpdate === "tool_call") {
      // Most recent tool's title — what the chip shows while still running.
      if (update.title) liveLabel = update.title;
      lastToolStatus = update.status ?? undefined;
      const name = getToolName(update);
      if (name && grouping.subagentToolNames.has(name)) {
        counts.subagents++;
        addIcon(SUBAGENT_ICON, "subagent");
      } else if (readMcpToolDescriptor(update._meta)) {
        counts.other++;
        addIcon(MCP_ICON, "mcp");
      } else {
        const kind = update.kind ?? null;
        switch (kind) {
          case "execute":
            counts.execute++;
            break;
          case "read":
            counts.read++;
            break;
          case "edit":
            counts.edit++;
            break;
          case "delete":
            counts.delete++;
            break;
          case "move":
            counts.move++;
            break;
          case "search":
            counts.search++;
            break;
          case "fetch":
            counts.fetch++;
            break;
          default:
            counts.other++;
            break;
        }
        addIcon(iconForToolKind(kind), `kind:${kind ?? "other"}`);
      }
    } else if (
      update.sessionUpdate === "agent_message_chunk" ||
      update.sessionUpdate === "console"
    ) {
      counts.messages++;
    }
    // A thought still streaming at the end of the group means the agent is
    // actively thinking — the chip must not read as finished ("Worked").
    if (update.sessionUpdate === "agent_thought_chunk") {
      trailingThoughtStreaming = item.thoughtComplete === false;
    } else if (update.sessionUpdate === "tool_call") {
      trailingThoughtStreaming = false;
    }
  }

  if (trailingThoughtStreaming) liveLabel = "Thinking…";
  const active =
    trailingThoughtStreaming ||
    lastToolStatus === "pending" ||
    lastToolStatus === "in_progress";
  const hasCountableWork =
    counts.execute +
      counts.read +
      counts.edit +
      counts.delete +
      counts.move +
      counts.search +
      counts.fetch +
      counts.subagents +
      counts.other >
    0;
  return {
    counts,
    icons,
    liveLabel,
    active,
    hasCountableWork,
    doneLabel: buildDoneLabel(counts),
  };
}

// Completed turns are frozen by reference in the conversation builder, so their
// group summary never changes — cache it keyed on the group's (stable) first
// item to avoid re-walking every frozen group on every streamed token. The
// active (incomplete) turn is never cached, so its live label stays correct.
const summaryCache = new WeakMap<
  ConversationItem,
  { len: number; summary: GroupSummary }
>();

/**
 * `summarize`, skipping the walk for a run whose turn has completed. Exported so callers rendering
 * many groups per streamed chunk don't re-walk the settled ones.
 */
export function summarizeMemo(
  leading: ConversationItem[],
  turnComplete: boolean,
): GroupSummary {
  const key = leading[0];
  if (turnComplete) {
    const cached = summaryCache.get(key);
    if (cached && cached.len === leading.length) return cached.summary;
  }
  const summary = summarize(leading);
  if (turnComplete) summaryCache.set(key, { len: leading.length, summary });
  return summary;
}

/**
 * Transform the flat conversation items into rows for the new thread, folding
 * each turn's tool-call work into a collapsible group according to the global
 * per-group overrides. Emits the keepMounted indices and
 * item→row map in the same pass so callers don't re-walk the list.
 *
 * Safe to run on every render under useMemo; frozen-turn summaries are cached.
 */
export function buildThreadGroups(
  items: ConversationItem[],
  overrides: Record<string, boolean>,
): ThreadGrouping {
  const rows: ThreadRow[] = [];
  const keepMounted: number[] = [];
  const idToRowIndex = new Map<string, number>();
  let buffer: ConversationItem[] = [];

  const pushItemRow = (item: ConversationItem): number => {
    const idx = rows.length;
    rows.push({ kind: "item", id: item.id, item });
    idToRowIndex.set(item.id, idx);
    return idx;
  };

  const flush = () => {
    if (buffer.length === 0) return;
    const leading = buffer;
    const first = leading[0];
    const turnComplete =
      first.type === "session_update" && first.turnContext.turnComplete;
    const groupId = `group:${first.id}`;

    // Groups collapse by default; a per-group override (true=expanded) wins. No chip for a group
    // with no countable tool work (e.g. a lone streaming thought): folding it would hide the only
    // thing happening behind a meaningless "Worked" chip.
    const summary = summarizeMemo(leading, turnComplete);
    const expanded = overrides[groupId] ?? false;
    const chipPresent = summary.hasCountableWork;

    if (chipPresent) {
      // The chip owns its children (rendered inside one bordered box when
      // expanded), so they are NOT emitted as separate rows here. Their ids
      // still map to the group's row so find-in-thread can scroll to them.
      const idx = rows.length;
      rows.push({
        kind: "tool_group",
        id: groupId,
        items: leading,
        summary,
        turnComplete,
        expanded,
      });
      for (const item of leading) idToRowIndex.set(item.id, idx);
    } else {
      for (const item of leading) pushItemRow(item);
    }
    buffer = [];
  };

  for (const item of items) {
    if (isUserInitiatedConversationItem(item)) {
      flush();
      pushItemRow(item);
      continue;
    }
    switch (item.type) {
      case "session_update": {
        if (isGroupableItem(item)) {
          buffer.push(item);
        } else if (grouping.excludeMcpApps && isMcpToolItem(item)) {
          // Keep MCP-app tool calls standalone so their iframes stay mounted.
          flush();
          keepMounted.push(pushItemRow(item));
        } else {
          // Setup/clone progress, the agent's direct messages, and plans never
          // collapse into a group — they surface as their own chat rows.
          flush();
          pushItemRow(item);
        }
        break;
      }
      default: {
        // git_action_result, turn_cancelled, user_shell_execute, queued —
        // standalone rows that belong to the current turn's epilogue.
        flush();
        pushItemRow(item);
        break;
      }
    }
  }
  flush();

  return { rows, keepMounted, idToRowIndex };
}
