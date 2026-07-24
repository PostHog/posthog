import { randomUUID } from "node:crypto";
import * as fs from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import type { ContentBlock } from "@agentclientprotocol/sdk";
import { DEFAULT_GATEWAY_MODEL } from "../../../gateway-models";
import type { PostHogAPIClient } from "../../../posthog-api";
import type { StoredEntry } from "../../../types";
import { isEmptyContentBlock } from "../../../utils/acp-content";
import { neutralizeUnprocessableImages } from "../image-sanitization";
import { supports1MContext } from "./models";

export interface ConversationTurn {
  role: "user" | "assistant";
  content: ContentBlock[];
  toolCalls?: ToolCallInfo[];
}

export interface HydrateSessionJsonlResult {
  hasSession: boolean;
  conversation?: ConversationTurn[];
}

interface ToolCallInfo {
  toolCallId: string;
  toolName: string;
  input: unknown;
  result?: unknown;
}

interface JsonlConfig {
  sessionId: string;
  cwd: string;
  model?: string;
  version?: string;
  gitBranch?: string;
  slug?: string;
  permissionMode?: string;
}

interface ClaudeCodeMeta {
  toolCallId?: string;
  toolName?: string;
  toolInput?: unknown;
  toolResponse?: unknown;
}

interface SessionUpdate {
  sessionUpdate: string;
  content?: ContentBlock | ContentBlock[];
  _meta?: { claudeCode?: ClaudeCodeMeta };
  // ACP puts these on the update itself; _meta.claudeCode only reliably
  // carries toolName (and sometimes toolResponse).
  toolCallId?: string;
  rawInput?: unknown;
  rawOutput?: unknown;
}

// Individual tool payloads can be huge (whole-file Write inputs, full test
// output). Cap each one so a single call can't dominate the resume budget.
const MAX_TOOL_PAYLOAD_CHARS = 10_000;

function capToolPayload(value: unknown): unknown {
  const text = typeof value === "string" ? value : JSON.stringify(value);
  if (typeof text !== "string" || text.length <= MAX_TOOL_PAYLOAD_CHARS) {
    return value;
  }
  const preview = `${text.slice(0, MAX_TOOL_PAYLOAD_CHARS)}… [truncated ${text.length - MAX_TOOL_PAYLOAD_CHARS} chars]`;
  // tool_use.input must stay an object per the Claude API schema — wrap
  // instead of replacing with a bare string.
  return typeof value === "string"
    ? preview
    : { _truncated: true, preview, originalSize: text.length };
}

function isEmptyRecord(value: unknown): boolean {
  return (
    typeof value === "object" &&
    value !== null &&
    !Array.isArray(value) &&
    Object.keys(value).length === 0
  );
}

const MAX_PROJECT_KEY_LENGTH = 200;

function hashString(s: string): string {
  let hash = 0;
  for (let i = 0; i < s.length; i++) {
    hash = (hash << 5) - hash + s.charCodeAt(i);
    hash |= 0;
  }
  return Math.abs(hash).toString(36);
}

export function encodeCwdToProjectKey(cwd: string): string {
  let projectKey = cwd.replace(/[^a-zA-Z0-9]/g, "-");
  if (projectKey.length > MAX_PROJECT_KEY_LENGTH) {
    projectKey = `${projectKey.slice(0, MAX_PROJECT_KEY_LENGTH)}-${hashString(cwd)}`;
  }
  return projectKey;
}

export function getSessionJsonlPath(sessionId: string, cwd: string): string {
  const configDir =
    process.env.CLAUDE_CONFIG_DIR || path.join(os.homedir(), ".claude");
  return path.join(
    configDir,
    "projects",
    encodeCwdToProjectKey(cwd),
    `${sessionId}.jsonl`,
  );
}

export function rebuildConversation(
  entries: StoredEntry[],
): ConversationTurn[] {
  const turns: ConversationTurn[] = [];
  let currentAssistantContent: ContentBlock[] = [];
  let currentToolCalls: ToolCallInfo[] = [];

  for (const entry of entries) {
    const method = entry.notification?.method;
    const params = entry.notification?.params as Record<string, unknown>;

    if (method === "session/update" && params?.update) {
      const update = params.update as SessionUpdate;

      switch (update.sessionUpdate) {
        case "user_message":
        case "user_message_chunk": {
          if (
            currentAssistantContent.length > 0 ||
            currentToolCalls.length > 0
          ) {
            turns.push({
              role: "assistant",
              content: currentAssistantContent,
              toolCalls:
                currentToolCalls.length > 0 ? currentToolCalls : undefined,
            });
            currentAssistantContent = [];
            currentToolCalls = [];
          }

          const content = update.content;
          const contentArray = Array.isArray(content)
            ? content
            : content
              ? [content]
              : [];

          const lastTurn = turns[turns.length - 1];
          if (lastTurn?.role === "user") {
            lastTurn.content.push(...contentArray);
          } else {
            turns.push({ role: "user", content: contentArray });
          }
          break;
        }

        case "agent_message":
        case "agent_message_chunk":
        case "agent_thought_chunk": {
          const content = update.content;
          if (
            content &&
            !Array.isArray(content) &&
            !isEmptyContentBlock(content)
          ) {
            if (
              content.type === "text" &&
              currentAssistantContent.length > 0 &&
              currentAssistantContent[currentAssistantContent.length - 1]
                .type === "text"
            ) {
              const lastBlock = currentAssistantContent[
                currentAssistantContent.length - 1
              ] as { type: "text"; text: string };
              lastBlock.text += (
                content as { type: "text"; text: string }
              ).text;
            } else {
              currentAssistantContent.push(content);
            }
          }
          break;
        }

        case "tool_call":
        case "tool_call_update": {
          const meta = update._meta?.claudeCode;
          const toolCallId = update.toolCallId ?? meta?.toolCallId;
          if (!toolCallId) break;

          let toolCall = currentToolCalls.find(
            (tc) => tc.toolCallId === toolCallId,
          );
          if (!toolCall) {
            const toolName = meta?.toolName;
            // Bare streaming updates carry no name; the opening tool_call
            // always does, so the call exists by the time they arrive.
            if (!toolName) break;
            toolCall = { toolCallId, toolName, input: {} };
            currentToolCalls.push(toolCall);
          }

          const input = update.rawInput ?? meta?.toolInput;
          // The opening tool_call ships rawInput: {} — don't clobber an
          // already-streamed input with it.
          if (input !== undefined && !isEmptyRecord(input)) {
            toolCall.input = capToolPayload(input);
          }
          const result = update.rawOutput ?? meta?.toolResponse;
          if (result !== undefined) {
            toolCall.result = capToolPayload(result);
          }
          break;
        }

        case "tool_result": {
          const meta = update._meta?.claudeCode;
          const toolCallId = update.toolCallId ?? meta?.toolCallId;
          if (toolCallId) {
            const toolCall = currentToolCalls.find(
              (tc) => tc.toolCallId === toolCallId,
            );
            const result = update.rawOutput ?? meta?.toolResponse;
            if (toolCall && result !== undefined) {
              toolCall.result = capToolPayload(result);
            }
          }
          break;
        }
      }
    }
  }

  if (currentAssistantContent.length > 0 || currentToolCalls.length > 0) {
    turns.push({
      role: "assistant",
      content: currentAssistantContent,
      toolCalls: currentToolCalls.length > 0 ? currentToolCalls : undefined,
    });
  }

  return turns;
}

// JSON-heavy tool payloads tokenize at ~2.5-3 chars/token, so estimate low.
const CHARS_PER_TOKEN = 3;
// Target ~half the context window, leaving headroom for the system prompt,
// tools, skills, estimation error, and the resumed run's own work.
const DEFAULT_MAX_TOKENS = 80_000;
const LARGE_CONTEXT_MAX_TOKENS = 400_000;

function estimateTurnTokens(turn: ConversationTurn): number {
  let chars = 0;
  for (const block of turn.content) {
    if ("text" in block && typeof block.text === "string") {
      chars += block.text.length;
    }
  }
  if (turn.toolCalls) {
    for (const tc of turn.toolCalls) {
      chars += JSON.stringify(tc.input ?? "").length;
      if (tc.result !== undefined) {
        chars +=
          typeof tc.result === "string"
            ? tc.result.length
            : JSON.stringify(tc.result).length;
      }
    }
  }
  return Math.ceil(chars / CHARS_PER_TOKEN);
}

export function selectRecentTurns(
  turns: ConversationTurn[],
  maxTokens = DEFAULT_MAX_TOKENS,
): ConversationTurn[] {
  let budget = maxTokens;
  let startIndex = turns.length;

  for (let i = turns.length - 1; i >= 0; i--) {
    const cost = estimateTurnTokens(turns[i]);
    if (cost > budget) break;
    budget -= cost;
    startIndex = i;
  }

  if (startIndex === turns.length && turns.length > 0) {
    // Even the most recent turn alone exceeds the budget — typical for a
    // single-prompt run, where everything after the prompt is one giant
    // assistant turn. Resuming with nothing loses all context, so keep the
    // nearest user turn (the task intent) and shed the assistant turn's
    // oldest tool calls until it fits.
    return selectOversizedTailFallback(turns, maxTokens);
  }

  // Ensure we start on a user turn so the conversation is well-formed
  while (startIndex < turns.length && turns[startIndex].role !== "user") {
    startIndex++;
  }

  return turns.slice(startIndex);
}

function selectOversizedTailFallback(
  turns: ConversationTurn[],
  maxTokens: number,
): ConversationTurn[] {
  const last = turns[turns.length - 1];

  let userIndex = turns.length - 1;
  while (userIndex >= 0 && turns[userIndex].role !== "user") {
    userIndex--;
  }

  const selected: ConversationTurn[] = [];
  let budget = maxTokens;
  if (userIndex >= 0) {
    selected.push(turns[userIndex]);
    budget -= estimateTurnTokens(turns[userIndex]);
  }
  if (userIndex !== turns.length - 1) {
    selected.push(dropOldestToolCalls(last, Math.max(budget, 0)));
  }
  return selected;
}

function dropOldestToolCalls(
  turn: ConversationTurn,
  budget: number,
): ConversationTurn {
  if (!turn.toolCalls?.length) return turn;
  const toolCalls = [...turn.toolCalls];
  const trimmed: ConversationTurn = { ...turn, toolCalls };
  while (toolCalls.length > 0 && estimateTurnTokens(trimmed) > budget) {
    toolCalls.shift();
  }
  if (toolCalls.length === 0) {
    trimmed.toolCalls = undefined;
  }
  return trimmed;
}

const BASE62 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";

function generateMessageId(): string {
  const bytes = new Uint8Array(24);
  crypto.getRandomValues(bytes);
  let id = "msg_01";
  for (const b of bytes) {
    id += BASE62[b % 62];
  }
  return id;
}

const ADJECTIVES = [
  "bright",
  "calm",
  "daring",
  "eager",
  "fair",
  "gentle",
  "happy",
  "keen",
  "lively",
  "merry",
  "noble",
  "polite",
  "quick",
  "sharp",
  "warm",
  "witty",
];
const VERBS = [
  "blazing",
  "crafting",
  "dashing",
  "flowing",
  "gliding",
  "humming",
  "jumping",
  "linking",
  "melting",
  "nesting",
  "pacing",
  "roaming",
  "sailing",
  "turning",
  "waving",
  "zoning",
];
const NOUNS = [
  "aurora",
  "breeze",
  "cedar",
  "delta",
  "ember",
  "frost",
  "grove",
  "haven",
  "inlet",
  "jewel",
  "knoll",
  "lotus",
  "maple",
  "nexus",
  "oasis",
  "prism",
];

function generateSlug(): string {
  const pick = (arr: string[]) => arr[Math.floor(Math.random() * arr.length)];
  return `${pick(ADJECTIVES)}-${pick(VERBS)}-${pick(NOUNS)}`;
}

export function conversationTurnsToJsonlEntries(
  turns: ConversationTurn[],
  config: JsonlConfig,
): string[] {
  const lines: string[] = [];
  let parentUuid: string | null = null;
  const model = config.model ?? DEFAULT_GATEWAY_MODEL;
  const version = config.version ?? "2.1.63";
  const gitBranch = config.gitBranch ?? "";
  const slug = config.slug ?? generateSlug();
  const permissionMode = config.permissionMode ?? "default";
  const baseTime = Date.now() - turns.length * 3000;
  let turnIndex = 0;

  for (const turn of turns) {
    const timestamp = new Date(baseTime + turnIndex * 3000).toISOString();
    turnIndex++;
    if (turn.role === "user") {
      lines.push(
        JSON.stringify({
          type: "queue-operation",
          operation: "enqueue",
          timestamp,
          sessionId: config.sessionId,
        }),
      );
      lines.push(
        JSON.stringify({
          type: "queue-operation",
          operation: "dequeue",
          timestamp,
          sessionId: config.sessionId,
        }),
      );

      const uuid = randomUUID();
      const textParts = turn.content
        .filter(
          (block) =>
            "text" in block && typeof block.text === "string" && block.text,
        )
        .map((block) => (block as { text: string }).text);

      const userText = textParts.length > 0 ? textParts.join("") : " ";

      lines.push(
        JSON.stringify({
          parentUuid,
          isSidechain: false,
          userType: "external",
          cwd: config.cwd,
          sessionId: config.sessionId,
          version,
          gitBranch,
          slug,
          type: "user",
          message: {
            role: "user",
            content: [{ type: "text", text: userText }],
          },
          uuid,
          timestamp,
          permissionMode,
        }),
      );
      parentUuid = uuid;
    } else {
      const allBlocks: unknown[] = [];

      for (const block of turn.content) {
        const blockType = (block as { type: string }).type;
        if (
          (blockType === "thinking" || blockType === "text") &&
          !isEmptyContentBlock(block)
        ) {
          allBlocks.push(block);
        }
      }

      if (turn.toolCalls) {
        for (const tc of turn.toolCalls) {
          allBlocks.push({
            type: "tool_use",
            id: tc.toolCallId,
            name: tc.toolName,
            // undefined would be dropped on stringify; the API requires input
            input: tc.input ?? {},
          });
        }
      }

      const msgId = generateMessageId();
      const hasToolUse = allBlocks.some(
        (b) => (b as { type: string }).type === "tool_use",
      );
      const lastStopReason = hasToolUse ? "tool_use" : "end_turn";

      for (let i = 0; i < allBlocks.length; i++) {
        const block = allBlocks[i];
        const isLast = i === allBlocks.length - 1;
        const uuid = randomUUID();

        lines.push(
          JSON.stringify({
            parentUuid,
            isSidechain: false,
            userType: "external",
            cwd: config.cwd,
            sessionId: config.sessionId,
            version,
            gitBranch,
            slug,
            type: "assistant",
            message: {
              model,
              id: msgId,
              type: "message",
              role: "assistant",
              content: [block],
              stop_reason: isLast ? lastStopReason : null,
              stop_sequence: null,
              usage: {
                input_tokens: 0,
                cache_creation_input_tokens: 0,
                cache_read_input_tokens: 0,
                output_tokens: 0,
              },
            },
            uuid,
            timestamp,
          }),
        );
        parentUuid = uuid;
      }

      if (turn.toolCalls) {
        for (const tc of turn.toolCalls) {
          if (tc.result === undefined) continue;

          const uuid = randomUUID();
          const resultText =
            typeof tc.result === "string"
              ? tc.result
              : JSON.stringify(tc.result);

          lines.push(
            JSON.stringify({
              parentUuid,
              isSidechain: false,
              userType: "external",
              cwd: config.cwd,
              sessionId: config.sessionId,
              version,
              gitBranch,
              slug,
              type: "user",
              message: {
                role: "user",
                content: [
                  {
                    type: "tool_result",
                    tool_use_id: tc.toolCallId,
                    content: resultText,
                  },
                ],
              },
              uuid,
              timestamp,
            }),
          );
          parentUuid = uuid;
        }
      }
    }
  }

  return lines;
}

interface HydrationLog {
  info: (msg: string, data?: unknown) => void;
  warn: (msg: string, data?: unknown) => void;
}

// Heals a persisted transcript that would otherwise 400 on every resume:
// empty content blocks, missing tool_use.input, and images the API can't
// process (unsupported type or over the per-image byte limit). The image case
// is why a session that once read/attached a bad image keeps re-triggering the
// same error on nearly every subsequent turn until the block is neutralized.
export async function sanitizeSessionJsonl(
  jsonlPath: string,
): Promise<boolean> {
  let raw: string;
  let statBefore: { mtimeMs: number; size: number };
  try {
    statBefore = await fs.stat(jsonlPath);
    raw = await fs.readFile(jsonlPath, "utf8");
  } catch {
    return false;
  }

  let changed = false;
  const sanitized = raw.split("\n").map((line) => {
    if (!line.trim()) return line;
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(line);
    } catch {
      return line;
    }
    const message = parsed.message as { content?: unknown } | undefined;
    if (!message || !Array.isArray(message.content)) return line;
    let lineChanged = false;
    const kept = message.content.filter((block) => !isEmptyContentBlock(block));
    if (kept.length !== message.content.length) {
      lineChanged = true;
      message.content = kept.length > 0 ? kept : [{ type: "text", text: " " }];
    }
    for (const block of message.content as (Record<string, unknown> | null)[]) {
      if (block?.type === "tool_use" && block.input == null) {
        block.input = {};
        lineChanged = true;
      }
    }
    const imageResult = neutralizeUnprocessableImages(message.content);
    if (imageResult.changed) {
      message.content = imageResult.value;
      lineChanged = true;
    }
    if (!lineChanged) return line;
    changed = true;
    return JSON.stringify(parsed);
  });

  if (!changed) return false;

  const tmpPath = `${jsonlPath}.tmp.${Date.now()}`;
  let renamed = false;
  try {
    await fs.writeFile(tmpPath, sanitized.join("\n"));
    // A concurrent writer may still own the file; abort rather than clobber
    // lines appended since the read. The next resume retries.
    const statNow = await fs.stat(jsonlPath);
    if (
      statNow.mtimeMs !== statBefore.mtimeMs ||
      statNow.size !== statBefore.size
    ) {
      return false;
    }
    await fs.rename(tmpPath, jsonlPath);
    renamed = true;
    return true;
  } finally {
    if (!renamed) {
      await fs.unlink(tmpPath).catch(() => {});
    }
  }
}

export async function hydrateSessionJsonl(params: {
  sessionId: string;
  cwd: string;
  taskId: string;
  runId: string;
  model?: string;
  gitBranch?: string;
  permissionMode?: string;
  posthogAPI: PostHogAPIClient;
  log: HydrationLog;
}): Promise<HydrateSessionJsonlResult> {
  const { posthogAPI, log } = params;

  try {
    const jsonlPath = getSessionJsonlPath(params.sessionId, params.cwd);
    try {
      await fs.access(jsonlPath);
      try {
        if (await sanitizeSessionJsonl(jsonlPath)) {
          log.info(
            "Healed existing session JSONL (empty and/or unprocessable-image blocks)",
            { jsonlPath },
          );
        }
      } catch (err) {
        // A sanitize failure must not block resuming from the existing file.
        log.warn("Failed to sanitize existing session JSONL", {
          jsonlPath,
          error: err instanceof Error ? err.message : String(err),
        });
      }
      return { hasSession: true };
    } catch {
      // File doesn't exist, proceed with hydration
    }

    const taskRun = await posthogAPI.getTaskRun(params.taskId, params.runId);
    if (!taskRun.log_url) {
      log.info("No log URL, skipping JSONL hydration");
      return { hasSession: false };
    }

    const entries = await posthogAPI.fetchTaskRunLogs(taskRun);
    if (entries.length === 0) {
      log.info("No S3 log entries, skipping JSONL hydration");
      return { hasSession: false };
    }

    const entryCounts: Record<string, number> = {};
    for (const entry of entries) {
      const method = entry.notification?.method ?? "unknown";
      const entryParams = entry.notification?.params as
        | Record<string, unknown>
        | undefined;
      const update = entryParams?.update as
        | { sessionUpdate?: string }
        | undefined;
      const key = update?.sessionUpdate
        ? `${method}:${update.sessionUpdate}`
        : method;
      entryCounts[key] = (entryCounts[key] ?? 0) + 1;
    }
    log.info("S3 log entry breakdown", {
      totalEntries: entries.length,
      types: entryCounts,
    });

    const allTurns = rebuildConversation(entries);

    if (allTurns.length === 0) {
      log.info("No conversation to hydrate, skipping JSONL hydration");
      return { hasSession: false };
    }

    const maxTokens = supports1MContext(params.model ?? "")
      ? LARGE_CONTEXT_MAX_TOKENS
      : DEFAULT_MAX_TOKENS;
    const conversation = selectRecentTurns(allTurns, maxTokens);
    log.info("Selected recent turns for hydration", {
      totalTurns: allTurns.length,
      selectedTurns: conversation.length,
      turnRoles: conversation.map((t) => t.role),
    });

    const jsonlLines = conversationTurnsToJsonlEntries(conversation, {
      sessionId: params.sessionId,
      cwd: params.cwd,
      model: params.model,
      gitBranch: params.gitBranch,
      permissionMode: params.permissionMode,
    });

    await fs.mkdir(path.dirname(jsonlPath), { recursive: true });

    const tmpPath = `${jsonlPath}.tmp.${Date.now()}`;
    await fs.writeFile(tmpPath, `${jsonlLines.join("\n")}\n`);
    await fs.rename(tmpPath, jsonlPath);

    log.info("Hydrated session JSONL from S3", {
      sessionId: params.sessionId,
      turns: conversation.length,
      lines: jsonlLines.length,
    });
    return { hasSession: true, conversation };
  } catch (err) {
    log.warn("Failed to hydrate session JSONL, continuing", {
      sessionId: params.sessionId,
      error: err instanceof Error ? err.message : String(err),
    });
    return { hasSession: false };
  }
}
