import type {
  SessionNotification,
  ToolCallContent,
  ToolCallLocation,
} from "@agentclientprotocol/sdk";
import { mcpToolKey, posthogToolMeta } from "@posthog/shared";
import { APP_SERVER_NOTIFICATIONS } from "./protocol";
import { readTokenUsage } from "./token-usage";

/**
 * Translates a native app-server notification into an ACP SessionNotification.
 * Streamed text maps to chunks; tool-like items map to `tool_call`/`tool_call_update`.
 * Agent-message and reasoning items are dropped — their deltas already streamed.
 */
export function mapAppServerNotification(
  sessionId: string,
  method: string,
  params: unknown,
): SessionNotification | null {
  switch (method) {
    case APP_SERVER_NOTIFICATIONS.AGENT_MESSAGE_DELTA: {
      const delta = readStringField(params, "delta");
      if (!delta) return null;
      return {
        sessionId,
        update: {
          sessionUpdate: "agent_message_chunk",
          content: { type: "text", text: delta },
        },
      };
    }
    case APP_SERVER_NOTIFICATIONS.REASONING_TEXT_DELTA:
    case APP_SERVER_NOTIFICATIONS.REASONING_SUMMARY_TEXT_DELTA: {
      const delta = readStringField(params, "delta");
      if (!delta) return null;
      return {
        sessionId,
        update: {
          sessionUpdate: "agent_thought_chunk",
          content: { type: "text", text: delta },
        },
      };
    }
    // Plan deltas are buffered by the adapter for the structured approval UI.
    case APP_SERVER_NOTIFICATIONS.PLAN_DELTA:
      return null;
    case APP_SERVER_NOTIFICATIONS.TOKEN_USAGE_UPDATED: {
      // Context indicator: renderer reads `used`/`size`; detailed breakdown comes via `_posthog/usage_update`.
      const usage = readTokenUsage(params);
      if (!usage) return null;
      // `usage_update` is a PostHog-convention update, not in the ACP union.
      return {
        sessionId,
        update: {
          sessionUpdate: "usage_update",
          used: usage.used,
          ...(usage.size != null ? { size: usage.size } : {}),
        },
      } as unknown as SessionNotification;
    }
    case APP_SERVER_NOTIFICATIONS.TURN_PLAN_UPDATED: {
      const plan = (
        params as { plan?: Array<{ step?: string; status?: string }> }
      )?.plan;
      if (!Array.isArray(plan)) return null;
      return {
        sessionId,
        update: {
          sessionUpdate: "plan",
          entries: plan.map((s) => ({
            content: s.step ?? "",
            priority: "medium",
            status: mapPlanStatus(s.status),
          })),
        },
      } as unknown as SessionNotification;
    }
    case APP_SERVER_NOTIFICATIONS.ITEM_STARTED:
    case APP_SERVER_NOTIFICATIONS.ITEM_COMPLETED: {
      const item = readItem(params);
      if (!item) return null;
      return mapItem(
        sessionId,
        item,
        method === APP_SERVER_NOTIFICATIONS.ITEM_COMPLETED,
      );
    }
    case APP_SERVER_NOTIFICATIONS.COMMAND_OUTPUT_DELTA: {
      const itemId = readStringField(params, "itemId");
      const delta = readStringField(params, "delta");
      if (!itemId || !delta) return null;
      return toolOutputChunk(sessionId, itemId, delta);
    }
    case APP_SERVER_NOTIFICATIONS.TERMINAL_INTERACTION: {
      const itemId = readStringField(params, "itemId");
      const stdin = readStringField(params, "stdin");
      if (!itemId || !stdin) return null;
      return toolOutputChunk(sessionId, itemId, stdin);
    }
    case APP_SERVER_NOTIFICATIONS.FILE_CHANGE_PATCH_UPDATED: {
      const itemId = readStringField(params, "itemId");
      if (!itemId) return null;
      const changes = (params as { changes?: AppServerItem["changes"] })
        ?.changes;
      const content = diffContent(changes);
      if (!content) return null;
      return {
        sessionId,
        update: {
          sessionUpdate: "tool_call_update",
          toolCallId: itemId,
          status: "in_progress",
          content,
        },
      };
    }
    default:
      return null;
  }
}

/** A streamed text chunk on an in-progress tool call; the renderer appends successive single-chunk updates. */
function toolOutputChunk(
  sessionId: string,
  toolCallId: string,
  text: string,
): SessionNotification {
  return {
    sessionId,
    update: {
      sessionUpdate: "tool_call_update",
      toolCallId,
      status: "in_progress",
      content: [{ type: "content", content: { type: "text", text } }],
    },
  };
}

function mapPlanStatus(
  status: string | undefined,
): "pending" | "in_progress" | "completed" {
  if (status === "inProgress") return "in_progress";
  if (status === "completed") return "completed";
  return "pending";
}

/**
 * Extracts {oldText,newText} from a unified diff so a codex `fileChange` renders as an ACP diff.
 * Cosmetic limit: a content line whose payload begins with "-- "/"++ " is misread as a header and dropped.
 */
export function parseUnifiedDiff(diff: string): {
  oldText: string;
  newText: string;
} {
  const oldLines: string[] = [];
  const newLines: string[] = [];
  for (const line of diff.split("\n")) {
    // Skip diff/hunk metadata; match trailing space on ---/+++ so content lines like "++i;" aren't dropped.
    if (
      line.startsWith("@@") ||
      line.startsWith("diff ") ||
      line.startsWith("index ") ||
      line.startsWith("--- ") ||
      line.startsWith("+++ ") ||
      line.startsWith("\\ ")
    ) {
      continue;
    }
    if (line.startsWith("-")) oldLines.push(line.slice(1));
    else if (line.startsWith("+")) newLines.push(line.slice(1));
    else {
      const ctx = line.startsWith(" ") ? line.slice(1) : line;
      oldLines.push(ctx);
      newLines.push(ctx);
    }
  }
  return { oldText: oldLines.join("\n"), newText: newLines.join("\n") };
}

export type AppServerItem = {
  type?: string;
  id?: string;
  command?: string;
  cwd?: string;
  commandActions?: Array<{ type?: string; path?: string } | string>;
  server?: string;
  tool?: string;
  namespace?: string | null;
  contentItems?: unknown;
  query?: string;
  status?: string;
  arguments?: unknown;
  aggregatedOutput?: string | null;
  changes?: Array<{ path?: string; diff?: string; kind?: unknown }>;
  result?: { content?: unknown } | null;
  error?: { message?: string } | null;
  // Present on message/reasoning items replayed from thread history.
  text?: string;
  content?: unknown;
  senderThreadId?: string;
  receiverThreadIds?: string[];
  prompt?: string | null;
  model?: string | null;
  reasoningEffort?: string | null;
  agentsStates?: Record<
    string,
    { status?: string; message?: string | null } | undefined
  >;
};

function mcpResultText(
  result: AppServerItem["result"],
  error: AppServerItem["error"],
): string | null {
  if (error?.message) return error.message;
  const content = result?.content;
  if (!Array.isArray(content)) return null;
  const text = content
    .filter(
      (c) =>
        c && typeof c === "object" && (c as { type?: string }).type === "text",
    )
    .map((c) => (c as { text?: string }).text ?? "")
    .filter(Boolean)
    .join("\n");
  return text || null;
}

function dynamicToolText(items: unknown): string | null {
  if (!Array.isArray(items)) return null;
  const text = items
    .filter(
      (c) =>
        c &&
        typeof c === "object" &&
        (c as { type?: string }).type === "inputText",
    )
    .map((c) => (c as { text?: string }).text ?? "")
    .filter(Boolean)
    .join("\n");
  return text || null;
}

/**
 * Re-renders a persisted `ThreadItem` as the ACP updates a live stream would have produced,
 * so a reattaching host shows the full transcript. Tool items collapse to one completed
 * `tool_call`; reasoning is not replayed.
 */
export function mapHistoryItem(
  sessionId: string,
  item: AppServerItem,
): SessionNotification[] {
  switch (item.type) {
    case "userMessage":
      return userMessageChunks(sessionId, item.content);
    case "agentMessage":
      return item.text
        ? [
            {
              sessionId,
              update: {
                sessionUpdate: "agent_message_chunk",
                content: { type: "text", text: item.text },
              },
            },
          ]
        : [];
    case "reasoning":
      return [];
    case "plan": {
      if (!item.text) return [];
      const toolCallId = `${item.id ?? "codex-plan"}:implement`;
      return [
        {
          sessionId,
          update: {
            sessionUpdate: "tool_call",
            toolCallId,
            title: "Plan",
            kind: "switch_mode",
            status: "completed",
            content: [
              {
                type: "content",
                content: { type: "text", text: item.text },
              },
            ],
            rawInput: { plan: item.text, historical: true },
          },
        },
      ];
    }
    default: {
      const tool = describeTool(item);
      if (!tool || !item.id) return [];
      const content = completedContent(item, tool);
      return [
        {
          sessionId,
          update: {
            sessionUpdate: "tool_call",
            toolCallId: item.id,
            title: tool.title,
            kind: tool.kind,
            status: mapStatus(item.status),
            ...(tool.rawInput !== undefined ? { rawInput: tool.rawInput } : {}),
            ...(tool.locations?.length ? { locations: tool.locations } : {}),
            ...(item.type === "collabAgentToolCall"
              ? {
                  _meta: posthogToolMeta({
                    toolName: collabAgentToolName(item.tool),
                  }),
                }
              : tool.mcp
                ? {
                    _meta: posthogToolMeta({
                      toolName: mcpToolKey(tool.mcp),
                      mcp: tool.mcp,
                    }),
                  }
                : {}),
            ...(content ? { content } : {}),
          },
        },
      ];
    }
  }
}

/** Replays a persisted `userMessage`'s text inputs; historical image attachments aren't re-rendered. */
function userMessageChunks(
  sessionId: string,
  content: unknown,
): SessionNotification[] {
  if (!Array.isArray(content)) return [];
  const out: SessionNotification[] = [];
  for (const block of content) {
    if (
      block &&
      typeof block === "object" &&
      (block as { type?: string }).type === "text"
    ) {
      const text = (block as { text?: string }).text;
      if (typeof text === "string" && text) {
        out.push({
          sessionId,
          update: {
            sessionUpdate: "user_message_chunk",
            content: { type: "text", text },
          },
        });
      }
    }
  }
  return out;
}

type ToolDescriptor = {
  title: string;
  kind: "execute" | "edit" | "fetch" | "other" | "read" | "search";
  rawInput?: unknown;
  output?: string | null;
  locations?: ToolCallLocation[];
  /** Originating MCP server + tool, surfaced on `_meta.posthog` so the renderer routes MCP rendering. */
  mcp?: { server: string; tool: string };
};

/** Classify a shell command by its actions so read-only commands render as read/search, not execute. */
function commandKind(
  actions: AppServerItem["commandActions"],
): "read" | "search" | "execute" {
  if (!actions?.length) return "execute";
  const types = actions.map((a) => (typeof a === "string" ? a : a?.type));
  if (types.every((t) => t === "read")) return "read";
  if (types.every((t) => t === "search" || t === "listFiles")) return "search";
  return "execute";
}

function describeTool(item: AppServerItem): ToolDescriptor | null {
  switch (item.type) {
    case "commandExecution":
      return {
        title: item.command ?? "Run command",
        kind: commandKind(item.commandActions),
        output: item.aggregatedOutput ?? null,
        locations: commandLocations(item),
      };
    case "fileChange": {
      const paths = changePaths(item.changes);
      return {
        title: fileChangeTitle(paths),
        kind: "edit",
        locations: paths.map((path) => ({ path })),
      };
    }
    case "mcpToolCall":
      return {
        title: `${item.server ?? "mcp"}/${item.tool ?? "tool"}`,
        kind: "other",
        rawInput: item.arguments,
        output: mcpResultText(item.result, item.error),
        mcp: { server: item.server ?? "mcp", tool: item.tool ?? "tool" },
      };
    case "dynamicToolCall":
      return {
        title: item.namespace
          ? `${item.namespace}/${item.tool ?? "tool"}`
          : (item.tool ?? "tool"),
        kind: "other",
        rawInput: item.arguments,
        output: dynamicToolText(item.contentItems),
      };
    case "collabAgentToolCall":
      if (item.tool === "wait" || item.tool === "closeAgent") {
        return null;
      }
      return {
        title: collabAgentTitle(item),
        kind: "other",
        rawInput: {
          ...(item.prompt ? { prompt: item.prompt } : {}),
          ...(item.receiverThreadIds?.length
            ? { receiverThreadIds: item.receiverThreadIds }
            : {}),
          ...(item.model ? { model: item.model } : {}),
          ...(item.reasoningEffort
            ? { reasoningEffort: item.reasoningEffort }
            : {}),
        },
      };
    case "webSearch":
      return { title: item.query ?? "Web search", kind: "fetch" };
    default:
      return null;
  }
}

function collabAgentTitle(item: AppServerItem): string {
  switch (item.tool) {
    case "spawnAgent":
      return item.prompt
        ? item.prompt.split("\n", 1)[0].slice(0, 120)
        : "Spawn subagent";
    case "sendInput":
      return "Message subagent";
    case "resumeAgent":
      return "Resume subagent";
    case "wait":
      return "Wait for subagents";
    case "closeAgent":
      return "Close subagent";
    default:
      return "Subagent";
  }
}

function collabAgentToolName(tool: string | undefined): string {
  switch (tool) {
    case "spawnAgent":
      return "spawn_agent";
    case "sendInput":
      return "send_input";
    case "resumeAgent":
      return "resume_agent";
    case "wait":
      return "wait_agent";
    case "closeAgent":
      return "close_agent";
    default:
      return "subagent";
  }
}

/** Distinct, non-empty changed paths for a fileChange item, order-preserved. */
export function changePaths(changes: AppServerItem["changes"]): string[] {
  if (!changes?.length) return [];
  const seen = new Set<string>();
  const paths: string[] = [];
  for (const change of changes) {
    const path = change?.path;
    if (path && !seen.has(path)) {
      seen.add(path);
      paths.push(path);
    }
  }
  return paths;
}

function fileChangeTitle(paths: string[]): string {
  if (!paths.length) return "Edit files";
  if (paths.length === 1) return paths[0];
  return `${paths[0]} (+${paths.length - 1} more)`;
}

/** Clickable locations for a commandExecution: action paths, else the cwd as a fallback. */
function commandLocations(item: AppServerItem): ToolCallLocation[] | undefined {
  const paths: string[] = [];
  const seen = new Set<string>();
  for (const action of item.commandActions ?? []) {
    const path = typeof action === "string" ? undefined : action?.path;
    if (path && !seen.has(path)) {
      seen.add(path);
      paths.push(path);
    }
  }
  if (!paths.length && item.cwd) paths.push(item.cwd);
  if (!paths.length) return undefined;
  return paths.map((path) => ({ path }));
}

function mapItem(
  sessionId: string,
  item: AppServerItem,
  completed: boolean,
): SessionNotification | null {
  const tool = describeTool(item);
  if (!tool || !item.id) {
    return null;
  }

  if (!completed) {
    return {
      sessionId,
      update: {
        sessionUpdate: "tool_call",
        toolCallId: item.id,
        title: tool.title,
        kind: tool.kind,
        status: "in_progress",
        ...(tool.rawInput !== undefined ? { rawInput: tool.rawInput } : {}),
        ...(tool.locations?.length ? { locations: tool.locations } : {}),
        ...(item.type === "collabAgentToolCall"
          ? {
              _meta: posthogToolMeta({
                toolName: collabAgentToolName(item.tool),
              }),
            }
          : tool.mcp
            ? {
                _meta: posthogToolMeta({
                  toolName: mcpToolKey(tool.mcp),
                  mcp: tool.mcp,
                }),
              }
            : {}),
      },
    };
  }

  const content = completedContent(item, tool);
  return {
    sessionId,
    update: {
      sessionUpdate: "tool_call_update",
      toolCallId: item.id,
      status: mapStatus(item.status),
      ...(content ? { content } : {}),
    },
  };
}

function completedContent(
  item: AppServerItem,
  tool: ToolDescriptor,
): ToolCallContent[] | undefined {
  if (item.type === "fileChange") {
    const diffs = diffContent(item.changes);
    if (diffs) return diffs;
  }
  if (tool.output) {
    return [{ type: "content", content: { type: "text", text: tool.output } }];
  }
  return undefined;
}

/** Maps a fileChange's `changes[]` to ACP `diff` content blocks. */
export function diffContent(
  changes: AppServerItem["changes"],
): ToolCallContent[] | undefined {
  if (!changes?.length) return undefined;
  const diffs = changes
    .filter((c) => c?.diff)
    .map(
      (c) =>
        ({
          type: "diff",
          path: c.path,
          ...parseUnifiedDiff(c.diff ?? ""),
        }) as unknown as ToolCallContent,
    );
  return diffs.length ? diffs : undefined;
}

function mapStatus(
  status: string | undefined,
): "completed" | "failed" | "in_progress" {
  if (status === "completed") return "completed";
  if (status === "failed" || status === "declined") return "failed";
  return "in_progress";
}

function readItem(params: unknown): AppServerItem | null {
  if (params && typeof params === "object" && "item" in params) {
    const item = (params as Record<string, unknown>).item;
    if (item && typeof item === "object") {
      return item as AppServerItem;
    }
  }
  return null;
}

function readStringField(params: unknown, key: string): string | null {
  if (params && typeof params === "object" && key in params) {
    const value = (params as Record<string, unknown>)[key];
    return typeof value === "string" ? value : null;
  }
  return null;
}
