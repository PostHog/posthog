import type {
  ToolCallContent,
  ToolCallLocation,
} from "@agentclientprotocol/sdk";
import {
  type AcpMessage,
  isBinaryFile,
  isJsonRpcNotification,
} from "@posthog/shared";
import type { ChangedFile } from "@posthog/shared/domain-types";

function getContentText(
  content: ToolCallContent[] | undefined,
): string | undefined {
  if (!content?.length) return undefined;
  for (const item of content) {
    if (item.type === "content" && item.content.type === "text") {
      return item.content.text;
    }
  }
  return undefined;
}

function getReadToolContent(
  content: ToolCallContent[] | undefined,
): string | undefined {
  const raw = getContentText(content);
  if (!raw) return undefined;

  let text = raw;
  text = text.replace(/<system-reminder>[\s\S]*?<\/system-reminder>/g, "");
  text = text.replace(/^```\w*\n?/, "").replace(/\n?```\s*$/, "");
  text = text
    .split("\n")
    .map((line) => line.replace(/^\s*\d+→/, ""))
    .join("\n");
  text = text.trim();

  return text || undefined;
}

export interface ParsedToolCall {
  toolCallId: string;
  kind?: string | null;
  title?: string;
  status?: string | null;
  locations?: ToolCallLocation[];
  content?: ToolCallContent[];
  rawOutput?: unknown;
}

/**
 * A Read whose file is unchanged since the agent's last read returns a
 * `file_unchanged` result (Claude Code's "Wasted call — ... Refer to that
 * earlier tool_result instead." sentinel) instead of the file body. Its
 * `content` is that sentinel message, not the file, so it must not be treated
 * as file content.
 */
function isFileUnchangedRead(toolCall: ParsedToolCall): boolean {
  const raw = toolCall.rawOutput;
  return (
    typeof raw === "object" &&
    raw !== null &&
    (raw as { type?: unknown }).type === "file_unchanged"
  );
}

// Match file paths that may differ in format (absolute vs relative)
function pathsMatch(a: string | undefined, b: string): boolean {
  if (!a) return false;
  if (a === b) return true;
  return a.endsWith(`/${b}`) || b.endsWith(`/${a}`);
}

function inferKind(kind?: string | null, title?: string): string | null {
  if (kind) return kind;
  if (!title) return null;

  const normalized = title.toLowerCase();
  if (normalized.startsWith("write")) return "write";
  if (normalized.startsWith("edit")) return "edit";
  if (normalized.startsWith("delete")) return "delete";
  if (normalized.startsWith("move") || normalized.startsWith("rename")) {
    return "move";
  }

  return null;
}

function mergeToolCall(
  existing: ParsedToolCall | undefined,
  patch: Partial<ParsedToolCall>,
): ParsedToolCall {
  return {
    toolCallId: patch.toolCallId ?? existing?.toolCallId ?? "",
    kind: patch.kind ?? existing?.kind,
    title: patch.title ?? existing?.title,
    status: patch.status ?? existing?.status,
    locations:
      patch.locations && patch.locations.length > 0
        ? patch.locations
        : existing?.locations,
    content:
      patch.content && patch.content.length > 0
        ? patch.content
        : existing?.content,
    rawOutput: patch.rawOutput ?? existing?.rawOutput,
  };
}

function getDiffContent(
  content: ToolCallContent[] | undefined,
): Extract<ToolCallContent, { type: "diff" }> | undefined {
  return content?.find(
    (item): item is Extract<ToolCallContent, { type: "diff" }> =>
      item.type === "diff",
  );
}

/**
 * diff stats with bag of lines, these are computed for every changed file whenever the session events update
 * so we want this to be fast
 */
function getDiffStats(
  oldText: string | null | undefined,
  newText: string | null | undefined,
): { added?: number; removed?: number } {
  if (!oldText && !newText) return {};

  const oldLines = oldText ? oldText.split("\n") : [];
  const newLines = newText ? newText.split("\n") : [];

  if (!oldText) {
    return { added: newLines.length, removed: 0 };
  }

  const oldCounts = new Map<string, number>();
  for (const line of oldLines) {
    oldCounts.set(line, (oldCounts.get(line) ?? 0) + 1);
  }

  const newCounts = new Map<string, number>();
  for (const line of newLines) {
    newCounts.set(line, (newCounts.get(line) ?? 0) + 1);
  }

  let added = 0;
  let removed = 0;

  for (const [line, count] of newCounts) {
    const oldCount = oldCounts.get(line) ?? 0;
    if (count > oldCount) added += count - oldCount;
  }

  for (const [line, count] of oldCounts) {
    const newCount = newCounts.get(line) ?? 0;
    if (count > newCount) removed += count - newCount;
  }

  return { added, removed };
}

const diffStatsCache = new WeakMap<
  Extract<ToolCallContent, { type: "diff" }>,
  { added?: number; removed?: number }
>();

export function cachedDiffStats(
  diff: Extract<ToolCallContent, { type: "diff" }> | undefined,
): { added?: number; removed?: number } {
  if (!diff) return {};
  const cached = diffStatsCache.get(diff);
  if (cached) return cached;
  const stats = getDiffStats(diff.oldText, diff.newText);
  diffStatsCache.set(diff, stats);
  return stats;
}

export interface CloudEventSummary {
  toolCalls: Map<string, ParsedToolCall>;
}

/**
 * Single-pass extraction of tool calls from events.
 */
export function buildCloudEventSummary(
  events: AcpMessage[],
): CloudEventSummary {
  const toolCalls = new Map<string, ParsedToolCall>();

  for (const event of events) {
    const message = event.message;
    if (!isJsonRpcNotification(message)) continue;

    if (message.method === "session/update") {
      const params = message.params as
        | { update?: Record<string, unknown> }
        | undefined;
      const update = params?.update;
      if (!update || typeof update !== "object") continue;

      const sessionUpdate = update.sessionUpdate;
      if (
        sessionUpdate !== "tool_call" &&
        sessionUpdate !== "tool_call_update"
      ) {
        continue;
      }

      const toolCallId =
        typeof update.toolCallId === "string" ? update.toolCallId : undefined;
      if (!toolCallId) continue;

      const patch: Partial<ParsedToolCall> = {
        toolCallId,
        kind: typeof update.kind === "string" ? update.kind : null,
        title: typeof update.title === "string" ? update.title : undefined,
        status: typeof update.status === "string" ? update.status : null,
        locations: Array.isArray(update.locations)
          ? (update.locations as ToolCallLocation[])
          : undefined,
        content: Array.isArray(update.content)
          ? (update.content as ToolCallContent[])
          : undefined,
        rawOutput: update.rawOutput,
      };

      const merged = mergeToolCall(toolCalls.get(toolCallId), patch);
      toolCalls.set(toolCallId, merged);
    }
  }

  return { toolCalls };
}

export function extractCloudFileDiff(
  toolCalls: Map<string, ParsedToolCall>,
  filePath: string,
): { oldText: string | null; newText: string | null } | null {
  // Iterate forward to compute cumulative diff:
  // oldText from the *first* tool call, newText from the *last*.
  let firstOldText: string | null | undefined;
  let lastNewText: string | null | undefined;
  let found = false;

  for (const toolCall of toolCalls.values()) {
    if (toolCall.status === "failed") continue;

    const kind = inferKind(toolCall.kind, toolCall.title);
    if (!kind || !["write", "edit", "delete", "move"].includes(kind)) continue;

    const diff = getDiffContent(toolCall.content);
    const locationPath = toolCall.locations?.[0]?.path;
    const destinationPath = toolCall.locations?.[1]?.path;
    const path =
      diff?.path ?? (kind === "move" ? destinationPath : locationPath);
    if (!pathsMatch(path, filePath)) continue;

    if (!found) {
      firstOldText = diff?.oldText ?? null;
      found = true;
    }
    lastNewText = diff?.newText ?? null;
  }

  if (!found) return null;

  return {
    oldText: firstOldText ?? null,
    newText: lastNewText ?? null,
  };
}

export function extractCloudToolChangedFiles(
  toolCalls: Map<string, ParsedToolCall>,
): ChangedFile[] {
  const filesByPath = new Map<string, ChangedFile>();

  for (const toolCall of toolCalls.values()) {
    if (toolCall.status === "failed") continue;

    const kind = inferKind(toolCall.kind, toolCall.title);
    if (!kind || !["write", "edit", "delete", "move"].includes(kind)) {
      continue;
    }

    const diff = getDiffContent(toolCall.content);
    const locationPath = toolCall.locations?.[0]?.path;
    const destinationPath = toolCall.locations?.[1]?.path;
    const path =
      diff?.path ?? (kind === "move" ? destinationPath : locationPath);
    if (!path) continue;
    if (path.includes(".claude/plans/")) continue;

    let file: ChangedFile;
    if (kind === "move") {
      file = {
        path,
        originalPath: locationPath,
        status: "renamed",
      };
    } else if (kind === "delete") {
      file = {
        path,
        status: "deleted",
      };
    } else {
      const diffStats = isBinaryFile(path) ? {} : cachedDiffStats(diff);
      file = {
        path,
        status: kind === "write" && !diff?.oldText ? "added" : "modified",
        linesAdded: diffStats.added,
        linesRemoved: diffStats.removed,
      };
    }

    // Delete and re-insert so the last tool call for a path appears at the end of iteration order
    if (filesByPath.has(path)) {
      filesByPath.delete(path);
    }
    filesByPath.set(path, file);
  }

  return [...filesByPath.values()];
}

export interface CloudFileContent {
  content: string | null;
  /** Whether the agent read, wrote, or deleted this file during the session. */
  touched: boolean;
}

/**
 * Combines read tool results and write/edit diffs to reconstruct the latest
 * known content for a file from a cloud session's tool calls.
 */
export function extractCloudFileContent(
  toolCalls: Map<string, ParsedToolCall>,
  filePath: string,
): CloudFileContent {
  let latestContent: string | null = null;
  let touched = false;

  for (const toolCall of toolCalls.values()) {
    if (toolCall.status === "failed") continue;

    const kind = inferKind(toolCall.kind, toolCall.title);
    const locationPath = toolCall.locations?.[0]?.path;

    if (kind === "read" && pathsMatch(locationPath, filePath)) {
      // A `file_unchanged` read carries the dedup sentinel, not the file body.
      if (isFileUnchangedRead(toolCall)) continue;
      const text = getReadToolContent(toolCall.content);
      if (text != null) {
        latestContent = text;
        touched = true;
      }
    } else if (kind === "delete" && pathsMatch(locationPath, filePath)) {
      latestContent = null;
      touched = true;
    } else if (kind === "move") {
      const destinationPath = toolCall.locations?.[1]?.path;
      if (
        pathsMatch(locationPath, filePath) ||
        pathsMatch(destinationPath, filePath)
      ) {
        const diff = getDiffContent(toolCall.content);
        if (diff?.newText != null) {
          latestContent = diff.newText;
        }
        touched = true;
      }
    } else if (kind && ["write", "edit"].includes(kind)) {
      const diff = getDiffContent(toolCall.content);
      const diffPath = diff?.path ?? locationPath;
      if (pathsMatch(diffPath, filePath) && diff?.newText != null) {
        latestContent = diff.newText;
        touched = true;
      }
    }
  }

  return { content: latestContent, touched };
}
