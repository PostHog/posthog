/**
 * Pure transformation functions for session data.
 * No side effects, no store access - just data transformations.
 */
import type {
  AvailableCommand,
  ContentBlock,
  SessionNotification,
} from "@agentclientprotocol/sdk";
import type {
  AcpMessage,
  JsonRpcMessage,
  JsonRpcRequest,
  StoredLogEntry,
  UserShellExecuteParams,
} from "@posthog/shared";
import {
  IMPORTED_USER_PROMPT_META_KEY,
  isJsonRpcNotification,
  isJsonRpcRequest,
} from "@posthog/shared";
import { skillTagsToSlashCommands } from "../message-editor/skillTags";
import { isNotification, POSTHOG_NOTIFICATIONS } from "./acpNotifications";
import { extractPromptDisplayContent } from "./promptContent";

export interface StoredLogEventPosition {
  taskRunId: string;
  entryIndex: number;
}

export interface StoredLogEventPositionOptions {
  taskRunId: string;
  startEntryIndex: number;
  firstPositionedEntryIndex?: number;
}

// Ordinals are local reconciliation provenance, so keep them out of the ACP
// event shape that crosses host and renderer boundaries.
const storedLogEventPositions = new WeakMap<
  AcpMessage,
  StoredLogEventPosition
>();

export function getStoredLogEventPosition(
  event: AcpMessage,
): StoredLogEventPosition | undefined {
  return storedLogEventPositions.get(event);
}

function recordStoredLogEventPosition(
  event: AcpMessage,
  position: StoredLogEventPosition | undefined,
): AcpMessage {
  if (position) storedLogEventPositions.set(event, position);
  return event;
}

/**
 * Convert a stored log entry to an ACP message.
 */
function storedEntryToAcpMessage(
  entry: StoredLogEntry,
  position?: StoredLogEventPosition,
): AcpMessage {
  const ts = entry.timestamp ? new Date(entry.timestamp).getTime() : Date.now();
  const promoted = promoteImportedUserPrompt(entry, ts);
  // Freeze at creation: events assigned via setSession bypass the store's
  // per-append freeze, so this keeps them read-only once stored.
  if (promoted) {
    return recordStoredLogEventPosition(Object.freeze(promoted), position);
  }
  return recordStoredLogEventPosition(
    Object.freeze({
      type: "acp_message",
      ts,
      message: (entry.notification ?? {}) as JsonRpcMessage,
    }),
    position,
  );
}

/**
 * A typed user prompt replayed from an imported Claude Code session arrives as
 * a `user_message_chunk` tagged with `_meta.importedUserPrompt`. The renderer
 * ignores raw user_message_chunks (live, user turns render from session/prompt
 * requests), so promote the tagged ones into a session/prompt user event. Only
 * affects imported sessions; normal logs carry no such marker.
 */
function promoteImportedUserPrompt(
  entry: StoredLogEntry,
  ts: number,
): AcpMessage | null {
  const notification = entry.notification as
    | { method?: string; params?: { update?: Record<string, unknown> } }
    | undefined;
  if (notification?.method !== "session/update") return null;
  const update = notification.params?.update;
  const meta = update?._meta as Record<string, unknown> | undefined;
  if (
    !update ||
    update.sessionUpdate !== "user_message_chunk" ||
    meta?.[IMPORTED_USER_PROMPT_META_KEY] !== true
  ) {
    return null;
  }
  const content = update.content as
    | { type?: string; text?: string }
    | undefined;
  if (content?.type !== "text" || !content.text) return null;
  return createUserMessageEvent(content.text, ts);
}

/**
 * Create a user message event for display.
 */
export function createUserPromptEvent(
  prompt: ContentBlock[],
  ts: number,
): AcpMessage {
  return {
    type: "acp_message",
    ts,
    message: {
      jsonrpc: "2.0",
      id: ts,
      method: "session/prompt",
      params: {
        prompt,
      },
    } as JsonRpcRequest,
  };
}

export function createUserMessageEvent(text: string, ts: number): AcpMessage {
  return createUserPromptEvent([{ type: "text", text }], ts);
}

/**
 * Create a user shell execute event.
 * When id is provided, it's used to track async execution (start/complete).
 * When result is undefined, it represents a command that's still running.
 */
export function createUserShellExecuteEvent(
  command: string,
  cwd: string,
  result?: { stdout: string; stderr: string; exitCode: number },
  id?: string,
): AcpMessage {
  return {
    type: "acp_message",
    ts: Date.now(),
    message: {
      jsonrpc: "2.0",
      method: "_array/user_shell_execute",
      params: { id, command, cwd, result },
    },
  };
}

/**
 * Collects completed user shell executes that occurred after the last prompt request.
 * These are included as hidden context in the next prompt so the agent
 * knows what commands the user ran between turns.
 *
 * Scans backwards from the end of events, stopping at the most recent
 * session/prompt request (not response), collecting any _array/user_shell_execute
 * notifications found along the way. Deduplicates by ID, keeping only completed executes.
 */
export function getUserShellExecutesSinceLastPrompt(
  events: AcpMessage[],
): UserShellExecuteParams[] {
  const execMap = new Map<string, UserShellExecuteParams>();

  for (let i = events.length - 1; i >= 0; i--) {
    const msg = events[i].message;

    if (isJsonRpcRequest(msg) && msg.method === "session/prompt") break;

    if (
      isJsonRpcNotification(msg) &&
      msg.method === "_array/user_shell_execute"
    ) {
      const params = msg.params as UserShellExecuteParams;
      if (params.result && params.id && !execMap.has(params.id)) {
        execMap.set(params.id, params);
      }
    }
  }

  return Array.from(execMap.values()).reverse();
}

/**
 * Convert shell executes to content blocks for prompt context.
 */
export function shellExecutesToContextBlocks(
  shellExecutes: UserShellExecuteParams[],
): ContentBlock[] {
  return shellExecutes
    .filter((cmd) => cmd.result)
    .map((cmd) => ({
      type: "text" as const,
      text: `[User executed command in ${cmd.cwd}]\n$ ${cmd.command}\n${
        cmd.result?.stdout || cmd.result?.stderr || "(no output)"
      }`,
      _meta: { ui: { hidden: true } },
    }));
}

/**
 * Convert stored log entries to ACP messages.
 * Optionally prepends a user message with the task description.
 */
function toolCallUpdateOf(
  event: AcpMessage,
): (Record<string, unknown> & { toolCallId: string }) | undefined {
  const msg = event.message;
  if (!isJsonRpcNotification(msg) || msg.method !== "session/update") {
    return undefined;
  }
  const update = (msg.params as SessionNotification | undefined)?.update as
    | { sessionUpdate?: string; toolCallId?: unknown }
    | undefined;
  if (update?.sessionUpdate !== "tool_call_update") return undefined;
  if (typeof update.toolCallId !== "string") return undefined;
  return update as Record<string, unknown> & { toolCallId: string };
}

/** Rebuild a (frozen) tool_call_update event around a replacement update. */
function withToolCallUpdate(
  event: AcpMessage,
  update: Record<string, unknown>,
): AcpMessage {
  const msg = event.message as { params?: SessionNotification };
  return recordStoredLogEventPosition(
    Object.freeze({
      ...event,
      message: {
        ...msg,
        params: { ...msg.params, update },
      } as JsonRpcMessage,
    }),
    getStoredLogEventPosition(event),
  );
}

/**
 * Collapse superseded `tool_call_update` snapshots into one merged update per
 * `toolCallId`, kept at the last update's position. Agents re-send the full
 * accumulated tool output on every update, so a long-running tool leaves
 * thousands of near-identical growing snapshots in a loaded transcript; one
 * 9k-update tool run carried ~312MB of tool content of which the merged
 * result is ~3MB.
 *
 * Updates are merged (shallow, later fields win) rather than dropped because
 * they carry different fields at different times — streamed `rawInput`
 * snapshots, input-derived title/content, edit diffs, then terminal
 * status/rawOutput — and the conversation reducer `Object.assign`s each one
 * into the tool call. Merging here reproduces exactly the state a full replay
 * would build; keeping only the last update would lose any field it doesn't
 * re-send (e.g. `rawInput` for every streamed call).
 */
export function collapseSupersededToolCallUpdates(
  events: AcpMessage[],
): AcpMessage[] {
  const firstIndexById = new Map<string, number>();
  const lastIndexById = new Map<string, number>();
  const mergedById = new Map<string, Record<string, unknown>>();
  for (let i = 0; i < events.length; i++) {
    const update = toolCallUpdateOf(events[i]);
    if (!update) continue;
    lastIndexById.set(update.toolCallId, i);
    const merged = mergedById.get(update.toolCallId);
    if (merged) {
      Object.assign(merged, update);
    } else {
      firstIndexById.set(update.toolCallId, i);
      mergedById.set(update.toolCallId, { ...update });
    }
  }
  if (lastIndexById.size === 0) return events;

  const collapsed: AcpMessage[] = [];
  for (let i = 0; i < events.length; i++) {
    const update = toolCallUpdateOf(events[i]);
    if (update) {
      const id = update.toolCallId;
      if (lastIndexById.get(id) !== i) continue;
      // A call with a single update needs no synthetic merge.
      if (firstIndexById.get(id) === i) {
        collapsed.push(events[i]);
      } else {
        const merged = mergedById.get(id);
        collapsed.push(
          merged ? withToolCallUpdate(events[i], merged) : events[i],
        );
      }
      continue;
    }
    collapsed.push(events[i]);
  }
  return collapsed;
}

export function convertStoredEntriesToEvents(
  entries: StoredLogEntry[],
  taskDescription?: string,
  positionOptions?: StoredLogEventPositionOptions,
): AcpMessage[] {
  const events: AcpMessage[] = [];

  if (taskDescription) {
    const startTs = entries[0]?.timestamp
      ? new Date(entries[0].timestamp).getTime() - 1
      : Date.now();
    events.push(createUserMessageEvent(taskDescription, startTs));
  }

  const firstPositionedEntryIndex =
    positionOptions?.firstPositionedEntryIndex ?? 0;
  for (let entryIndex = 0; entryIndex < entries.length; entryIndex += 1) {
    const position =
      positionOptions && entryIndex >= firstPositionedEntryIndex
        ? {
            taskRunId: positionOptions.taskRunId,
            entryIndex:
              positionOptions.startEntryIndex +
              entryIndex -
              firstPositionedEntryIndex,
          }
        : undefined;
    events.push(storedEntryToAcpMessage(entries[entryIndex], position));
  }

  return collapseSupersededToolCallUpdates(events);
}

/**
 * Extract available commands from session events.
 * Scans backwards to find the most recent available_commands_update.
 * Returns `null` if the agent has not emitted one yet — callers can use this
 * to distinguish "not yet received" from "received an empty list".
 */
export function extractAvailableCommandsFromEvents(
  events: AcpMessage[],
): AvailableCommand[] | null {
  for (let i = events.length - 1; i >= 0; i--) {
    const msg = events[i].message;
    if (
      "method" in msg &&
      msg.method === "session/update" &&
      !("id" in msg) &&
      "params" in msg
    ) {
      const params = msg.params as SessionNotification | undefined;
      const update = params?.update;
      if (update?.sessionUpdate === "available_commands_update") {
        return update.availableCommands || [];
      }
    }
  }
  return null;
}

/**
 * Extract user prompts from session events.
 * Returns an array of user prompt strings, most recent last.
 */
export function extractUserPromptsFromEvents(events: AcpMessage[]): string[] {
  const prompts: string[] = [];

  for (const event of events) {
    const msg = event.message;
    if (isJsonRpcRequest(msg) && msg.method === "session/prompt") {
      const params = msg.params as { prompt?: ContentBlock[] };
      if (params?.prompt?.length) {
        const { text, attachments } = extractPromptDisplayContent(
          params.prompt,
          { filterHidden: true },
        );

        if (text) {
          prompts.push(text);
        } else if (attachments.length > 0) {
          const labels = attachments.map((a) => a.label).join(", ");
          prompts.push(`[Attached files: ${labels}]`);
        }
      }
    }
  }

  return prompts;
}

export function extractPromptText(prompt: string | ContentBlock[]): string {
  if (typeof prompt === "string") return skillTagsToSlashCommands(prompt);
  return skillTagsToSlashCommands(extractPromptDisplayContent(prompt).text);
}

/**
 * Convert prompt input to ContentBlocks.
 */
export function normalizePromptToBlocks(
  prompt: string | ContentBlock[],
): ContentBlock[] {
  if (typeof prompt === "string") {
    return [{ type: "text", text: skillTagsToSlashCommands(prompt) }];
  }

  return prompt.map((block) =>
    block.type === "text"
      ? { ...block, text: skillTagsToSlashCommands(block.text) }
      : block,
  );
}

export { isFatalSessionError, isRateLimitError } from "@posthog/shared";

/**
 * Whether a list of events already contains a `session/prompt` request.
 */
export function hasSessionPromptEvent(events: AcpMessage[]): boolean {
  return events.some(
    (event) =>
      isJsonRpcRequest(event.message) &&
      event.message.method === "session/prompt",
  );
}

/**
 * Whether an event is a turn-complete notification.
 */
export function isTurnCompleteEvent(event: AcpMessage): boolean {
  const msg = event.message;
  return (
    "method" in msg &&
    isNotification(msg.method, POSTHOG_NOTIFICATIONS.TURN_COMPLETE)
  );
}

const FOLDER_TAG_REGEX = /<folder\s+path="([^"]+)"\s*\/>/g;

/**
 * Whether a path string looks like an absolute (or home-relative) folder path.
 */
export function isAbsoluteFolderPath(path: string): boolean {
  return (
    path.startsWith("/") || path.startsWith("~") || /^[A-Za-z]:[\\/]/.test(path)
  );
}

/**
 * Whether a prompt references an absolute folder via a `<folder path="…" />` tag.
 */
export function promptReferencesAbsoluteFolder(
  prompt: string | ContentBlock[],
): boolean {
  const text =
    typeof prompt === "string"
      ? prompt
      : prompt
          .map((block) =>
            "text" in block && typeof block.text === "string" ? block.text : "",
          )
          .join("");
  for (const match of text.matchAll(FOLDER_TAG_REGEX)) {
    if (isAbsoluteFolderPath(match[1])) return true;
  }
  return false;
}
