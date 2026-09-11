import {
  piSubagentToolDetailsSchema,
  readAgentToolName,
} from "@posthog/shared";
import type { ConversationItem } from "@posthog/ui/features/sessions/components/buildConversationItems";
import {
  isSubagentSpawnTool,
  isWorkflowTool,
} from "@posthog/ui/features/sessions/components/session-update/collaborationTools";

type GroupCounts = {
  execute: number;
  read: number;
  list: number;
  edit: number;
  delete: number;
  move: number;
  search: number;
  fetch: number;
  subagents: number;
  workflows: number;
  other: number;
};

type ToolGroupSummary = {
  doneLabel: string;
  hasCountableWork: boolean;
};

function getToolName(update: {
  _meta?: unknown;
  title?: string | null;
}): string | undefined {
  const toolName = readAgentToolName(update._meta);
  if (toolName) {
    return toolName;
  }
  return isSubagentSpawnTool(update.title) ? "subagent" : undefined;
}

function subagentCount(item: ConversationItem): number {
  if (item.type !== "session_update") {
    return 0;
  }

  const update = item.update;
  if (update.sessionUpdate !== "tool_call") {
    return 0;
  }

  const resolved = update.toolCallId
    ? item.turnContext.toolCalls.get(update.toolCallId)
    : undefined;
  const details = resolved?.details ?? update.details;
  const parsed = piSubagentToolDetailsSchema.safeParse(details);
  return parsed.success && parsed.data.results.length > 0
    ? parsed.data.results.length
    : 1;
}

function plural(n: number, singular: string, pluralForm: string): string {
  return `${n} ${n === 1 ? singular : pluralForm}`;
}

function files(n: number): string {
  return n === 1 ? "a file" : `${n} files`;
}

function buildDoneLabel(counts: GroupCounts): string {
  const segments: string[] = [];
  if (counts.execute > 0) {
    segments.push(`ran ${plural(counts.execute, "command", "commands")}`);
  }
  if (counts.read > 0) {
    segments.push(`read ${files(counts.read)}`);
  }
  if (counts.list > 0) {
    segments.push(`listed ${plural(counts.list, "directory", "directories")}`);
  }
  if (counts.edit > 0) {
    segments.push(`edited ${files(counts.edit)}`);
  }
  if (counts.delete > 0) {
    segments.push(`deleted ${files(counts.delete)}`);
  }
  if (counts.move > 0) {
    segments.push(`moved ${files(counts.move)}`);
  }
  if (counts.search > 0) {
    segments.push(`ran ${plural(counts.search, "search", "searches")}`);
  }
  if (counts.fetch > 0) {
    segments.push(`fetched ${plural(counts.fetch, "page", "pages")}`);
  }
  if (counts.subagents > 0) {
    segments.push(`ran ${plural(counts.subagents, "subagent", "subagents")}`);
  }
  if (counts.workflows === 1) {
    segments.push("ran a workflow");
  }
  if (counts.workflows > 1) {
    segments.push(`ran ${counts.workflows} workflows`);
  }
  if (counts.other > 0) {
    segments.push(plural(counts.other, "tool call", "tool calls"));
  }
  if (segments.length === 0) {
    return "Worked";
  }
  const joined = segments.join(", ");
  return joined.charAt(0).toUpperCase() + joined.slice(1);
}

function summarizeToolGroup(items: ConversationItem[]): ToolGroupSummary {
  const counts: GroupCounts = {
    execute: 0,
    read: 0,
    list: 0,
    edit: 0,
    delete: 0,
    move: 0,
    search: 0,
    fetch: 0,
    subagents: 0,
    workflows: 0,
    other: 0,
  };

  for (const item of items) {
    if (item.type !== "session_update") {
      continue;
    }
    const update = item.update;
    if (update.sessionUpdate !== "tool_call") {
      continue;
    }

    const name = getToolName(update);
    if (isWorkflowTool(name ?? update.title)) {
      counts.workflows++;
    } else if (isSubagentSpawnTool(name)) {
      counts.subagents += subagentCount(item);
    } else {
      switch (update.kind ?? null) {
        case "execute":
          counts.execute++;
          break;
        case "read":
          counts.read++;
          break;
        case "list":
          counts.list++;
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
    }
  }

  const hasCountableWork =
    counts.execute +
      counts.read +
      counts.list +
      counts.edit +
      counts.delete +
      counts.move +
      counts.search +
      counts.fetch +
      counts.subagents +
      counts.workflows +
      counts.other >
    0;
  return { doneLabel: buildDoneLabel(counts), hasCountableWork };
}

const summaryCache = new WeakMap<
  ConversationItem,
  { len: number; summary: ToolGroupSummary }
>();

export function summarizeToolGroupMemo(
  items: ConversationItem[],
  turnComplete: boolean,
): ToolGroupSummary {
  const key = items[0];
  if (turnComplete) {
    const cached = summaryCache.get(key);
    if (cached && cached.len === items.length) {
      return cached.summary;
    }
  }
  const summary = summarizeToolGroup(items);
  if (turnComplete) {
    summaryCache.set(key, { len: items.length, summary });
  }
  return summary;
}
