import {
  ArrowDown,
  Brain,
  CaretRight,
  CloudArrowDown,
  Robot,
} from "phosphor-react-native";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  Text,
  View,
} from "react-native";
import {
  AgentMessage,
  deriveToolKind,
  HumanMessage,
  ToolMessage,
  type ToolStatus,
} from "@/features/chat";
import { getRandomThinkingActivity } from "@/features/chat/utils/thinkingMessages";
import { useThemeColors } from "@/lib/theme";
import type {
  CloudPendingPermissionRequest,
  PlanEntry,
  SessionEvent,
  SessionNotification,
  SessionNotificationAttachment,
  TerminalStatus,
} from "../types";
import { CloudMessageAttachment } from "./CloudMessageAttachment";
import { PlanApprovalCard } from "./PlanApprovalCard";
import { PlanStatusBar } from "./PlanStatusBar";
import { QuestionCard } from "./QuestionCard";
import { TerminalStatusBanner } from "./TerminalStatusBanner";

interface PermissionResponseArgs {
  toolCallId: string;
  optionId: string;
  answers?: Record<string, string>;
  customInput?: string;
  displayText: string;
}

interface OptimisticUserMessage {
  text: string;
  attachments?: SessionNotificationAttachment[];
  // Submit-time epoch ms. Dedup only fires against user messages whose `ts`
  // is at or after this — protects against a text-identical historical turn
  // suppressing the new optimistic echo.
  setAt: number;
}

interface TaskSessionViewProps {
  events: SessionEvent[];
  taskId?: string;
  pendingPermissions?: Record<string, CloudPendingPermissionRequest>;
  isConnecting?: boolean;
  isThinking?: boolean;
  terminalStatus?: TerminalStatus;
  lastError?: string | null;
  onRetry?: () => void;
  onOpenTask?: (taskId: string) => void;
  onSendPermissionResponse?: (args: PermissionResponseArgs) => void;
  contentContainerStyle?: object;
  // Renders a user message at the bottom of the thread before the SSE echo
  // arrives — for the gap between submit and the live session catching up.
  // Suppressed automatically once a real user_message_chunk with matching
  // text appears in `events`.
  optimisticUserMessage?: OptimisticUserMessage;
}

interface ToolData {
  toolName: string;
  rawToolName?: string;
  toolCallId: string;
  status: ToolStatus;
  args?: Record<string, unknown>;
  result?: unknown;
  isAgent?: boolean;
  parentToolCallId?: string;
}

interface ParsedMessage {
  id: string;
  type: "user" | "agent" | "thought" | "tool" | "connecting" | "thinking";
  content: string;
  ts?: number;
  toolData?: ToolData;
  children?: ParsedMessage[];
  attachments?: SessionNotificationAttachment[];
}

function mapToolStatus(
  status?: "pending" | "in_progress" | "completed" | "failed" | null,
): ToolStatus {
  switch (status) {
    case "pending":
      return "pending";
    case "in_progress":
      return "running";
    case "completed":
      return "completed";
    case "failed":
      return "error";
    default:
      return "pending";
  }
}

type ParsedNotification =
  | {
      type: "user";
      content: string;
      attachments?: SessionNotificationAttachment[];
    }
  | { type: "agent" | "agent_complete" | "thought"; content: string }
  | { type: "tool" | "tool_update"; toolData: ToolData }
  | { type: "plan"; entries: PlanEntry[] };

function parseSessionNotification(
  notification: SessionNotification,
): ParsedNotification | null {
  const { update } = notification;
  if (!update?.sessionUpdate) {
    return null;
  }

  switch (update.sessionUpdate) {
    case "user_message_chunk":
    case "agent_message_chunk": {
      const hasText = update.content?.type === "text";
      const isUser = update.sessionUpdate === "user_message_chunk";
      if (isUser) {
        const attachments = update.attachments;
        // Drop only if there's neither text nor attachments to render.
        if (!hasText && (!attachments || attachments.length === 0)) {
          return null;
        }
        return {
          type: "user",
          content: hasText ? (update.content?.text ?? "") : "",
          attachments,
        };
      }
      if (hasText) {
        return {
          type: "agent",
          content: update.content?.text ?? "",
        };
      }
      return null;
    }
    // `agent_message` is the aggregated final message emitted by the server
    // once a response is complete. If we already received streaming chunks,
    // this is a duplicate — replace pending text instead of appending.
    case "agent_message": {
      if (update.content?.type === "text") {
        return {
          type: "agent_complete" as const,
          content: update.content.text,
        };
      }
      return null;
    }
    case "agent_thought_chunk": {
      if (update.content?.type === "text") {
        return { type: "thought", content: update.content.text };
      }
      return null;
    }
    case "tool_call": {
      const meta = update._meta?.claudeCode;
      const isAgent = meta?.toolName === "Agent" || meta?.toolName === "Task";
      return {
        type: "tool",
        toolData: {
          toolName: update.title ?? "Unknown Tool",
          rawToolName: meta?.toolName,
          toolCallId: update.toolCallId ?? "",
          status: mapToolStatus(update.status),
          args: update.rawInput,
          isAgent,
          parentToolCallId: meta?.parentToolCallId,
        },
      };
    }
    case "tool_call_update": {
      const meta = update._meta?.claudeCode;
      return {
        type: "tool_update",
        toolData: {
          toolName: update.title ?? "Unknown Tool",
          rawToolName: meta?.toolName,
          toolCallId: update.toolCallId ?? "",
          status: mapToolStatus(update.status),
          args: update.rawInput,
          result: update.rawOutput,
          parentToolCallId: meta?.parentToolCallId,
        },
      };
    }
    case "plan": {
      if (Array.isArray(update.entries)) {
        return { type: "plan", entries: update.entries };
      }
      return null;
    }
    default:
      return null;
  }
}

interface ProcessedEvents {
  messages: ParsedMessage[];
  plan: PlanEntry[] | null;
}

function isQuestionTool(toolData?: ToolData): boolean {
  if (!toolData) return false;
  if (toolData.toolName.toLowerCase().includes("question")) return true;
  if (Array.isArray(toolData.args?.questions)) return true;
  return false;
}

function hasPendingQuestionMessage(message: ParsedMessage): boolean {
  const isPendingQuestion =
    message.type === "tool" &&
    isQuestionTool(message.toolData) &&
    (message.toolData?.status === "pending" ||
      message.toolData?.status === "running");

  if (isPendingQuestion) {
    return true;
  }

  return message.children?.some(hasPendingQuestionMessage) ?? false;
}

function isPlanApprovalTool(
  toolData?: ToolData,
  permission?: CloudPendingPermissionRequest,
): boolean {
  if (permission?.toolCall.kind === "switch_mode") return true;
  if (toolData?.rawToolName === "ExitPlanMode") return true;
  return typeof toolData?.args?.plan === "string";
}

function isInteractivePermissionTool(
  toolData?: ToolData,
  permission?: CloudPendingPermissionRequest,
): boolean {
  return isQuestionTool(toolData) || isPlanApprovalTool(toolData, permission);
}

// Mutable processor state persisted across renders via useRef.
// Only new events (past processedIdx) are processed on each call.
interface EventProcessorState {
  messages: ParsedMessage[];
  plan: PlanEntry[] | null;
  pendingAgentText: string;
  pendingAgentTs?: number;
  pendingThoughtText: string;
  lastAgentMsgIdx: number | null;
  agentMessageCount: number;
  thoughtMessageCount: number;
  userMessageCount: number;
  toolMessages: Map<string, ParsedMessage>;
  // Maps agent toolCallId → agent ParsedMessage for nesting children
  agentTools: Map<string, ParsedMessage>;
  processedIdx: number;
  // Snapshot tracking: only create a new array ref when messages grow.
  // Mutations (tool_update, agent_complete replacing content) reuse the
  // same snapshot so FlatList doesn't re-layout and reset scroll position.
  lastSnapshot: ParsedMessage[];
  lastSnapshotLength: number;
}

function createProcessorState(): EventProcessorState {
  return {
    messages: [],
    plan: null,
    pendingAgentText: "",
    pendingThoughtText: "",
    lastAgentMsgIdx: null,
    agentMessageCount: 0,
    thoughtMessageCount: 0,
    userMessageCount: 0,
    toolMessages: new Map(),
    agentTools: new Map(),
    processedIdx: 0,
    lastSnapshot: [],
    lastSnapshotLength: 0,
  };
}

function processNewEvents(
  state: EventProcessorState,
  events: SessionEvent[],
): ProcessedEvents {
  // If events shrank (e.g. session reset), start fresh
  if (events.length < state.processedIdx) {
    Object.assign(state, createProcessorState());
  }

  // Nothing new to process
  if (events.length === state.processedIdx) {
    return { messages: state.messages, plan: state.plan };
  }

  let hasItemMutation = false;

  const flushAgentText = () => {
    if (!state.pendingAgentText) return;
    // If the last message is an in-progress agent message from a previous
    // batch, append to it instead of creating a new bubble. This keeps
    // streaming chunks that arrive across multiple SSE batches unified
    // into a single rendered message.
    if (
      state.lastAgentMsgIdx !== null &&
      state.messages[state.lastAgentMsgIdx]?.type === "agent"
    ) {
      state.messages[state.lastAgentMsgIdx].content += state.pendingAgentText;
      hasItemMutation = true;
    } else {
      const msg: ParsedMessage = {
        id: `agent-${state.agentMessageCount++}`,
        type: "agent",
        content: state.pendingAgentText,
        ts: state.pendingAgentTs,
      };
      state.messages.push(msg);
      state.lastAgentMsgIdx = state.messages.length - 1;
    }
    state.pendingAgentText = "";
    state.pendingAgentTs = undefined;
  };

  const flushThoughtText = () => {
    if (!state.pendingThoughtText) return;
    // Merge consecutive thoughts into one message instead of many rows
    const lastMsg = state.messages[state.messages.length - 1];
    if (lastMsg?.type === "thought") {
      lastMsg.content += state.pendingThoughtText;
    } else {
      state.messages.push({
        id: `thought-${state.thoughtMessageCount++}`,
        type: "thought",
        content: state.pendingThoughtText,
      });
    }
    state.pendingThoughtText = "";
  };

  const flushPending = () => {
    flushThoughtText();
    flushAgentText();
  };

  for (let i = state.processedIdx; i < events.length; i++) {
    const event = events[i];
    if (event.type !== "session_update") continue;

    const parsed = parseSessionNotification(event.notification);
    if (!parsed) continue;

    switch (parsed.type) {
      case "user":
        flushPending();
        state.messages.push({
          id: `user-${state.userMessageCount++}`,
          type: "user",
          content: parsed.content ?? "",
          ts: event.ts,
          attachments: parsed.attachments,
        });
        state.lastAgentMsgIdx = null;
        break;
      case "agent":
        flushThoughtText();
        if (!state.pendingAgentTs) state.pendingAgentTs = event.ts;
        state.pendingAgentText += parsed.content ?? "";
        break;
      case "agent_complete":
        flushThoughtText();
        // Replace accumulated chunks with the finalized message
        if (
          state.lastAgentMsgIdx !== null &&
          state.messages[state.lastAgentMsgIdx]?.type === "agent"
        ) {
          state.messages[state.lastAgentMsgIdx].content = parsed.content ?? "";
          if (!state.messages[state.lastAgentMsgIdx].ts) {
            state.messages[state.lastAgentMsgIdx].ts = event.ts;
          }
          hasItemMutation = true;
          state.pendingAgentText = "";
          state.pendingAgentTs = undefined;
        } else {
          state.pendingAgentText = parsed.content ?? "";
          if (!state.pendingAgentTs) state.pendingAgentTs = event.ts;
        }
        break;
      case "thought":
        flushAgentText();
        state.pendingThoughtText += parsed.content ?? "";
        break;
      case "plan":
        state.plan = parsed.entries;
        break;
      case "tool":
        flushPending();
        if (parsed.toolData) {
          const existing = state.toolMessages.get(parsed.toolData.toolCallId);
          if (existing?.toolData) {
            existing.toolData = {
              ...existing.toolData,
              ...parsed.toolData,
            };
          } else {
            const msg: ParsedMessage = {
              id: `tool-${parsed.toolData.toolCallId}`,
              type: "tool",
              content: "",
              toolData: parsed.toolData,
              children: parsed.toolData.isAgent ? [] : undefined,
            };
            state.toolMessages.set(parsed.toolData.toolCallId, msg);

            // Agent tools: register for child nesting
            if (parsed.toolData.isAgent) {
              state.agentTools.set(parsed.toolData.toolCallId, msg);
            }

            // Child tools: nest under parent agent instead of top-level
            const parentId = parsed.toolData.parentToolCallId;
            const parent = parentId
              ? state.agentTools.get(parentId)
              : undefined;
            if (parent?.children) {
              parent.children.push(msg);
              hasItemMutation = true;
            } else {
              state.messages.push(msg);
            }
          }
        }
        state.lastAgentMsgIdx = null;
        break;
      case "tool_update":
        if (parsed.toolData) {
          const existing = state.toolMessages.get(parsed.toolData.toolCallId);
          if (existing?.toolData) {
            existing.toolData.status = parsed.toolData.status;
            existing.toolData.result = parsed.toolData.result;
            if (parsed.toolData.args) {
              existing.toolData.args = parsed.toolData.args;
            }
            hasItemMutation = true;
          }
        }
        break;
    }
  }

  flushPending();
  state.processedIdx = events.length;

  // Create a new array reference when messages were added or when a tool
  // received args for the first time (so the diff view can render).
  // Pure status/text mutations reuse the prior snapshot to avoid jumps.
  if (state.messages.length !== state.lastSnapshotLength || hasItemMutation) {
    state.lastSnapshot = [...state.messages];
    state.lastSnapshotLength = state.messages.length;
  }

  return { messages: state.lastSnapshot, plan: state.plan };
}

const THOUGHT_COLLAPSED_LINE_COUNT = 5;

function CollapsedThought({ content }: { content: string }) {
  const themeColors = useThemeColors();
  const [expanded, setExpanded] = useState(false);
  const [showAllLines, setShowAllLines] = useState(false);

  const hasContent = content.trim().length > 0;
  const contentLines = content.split("\n");
  const isLineCollapsible =
    hasContent && contentLines.length > THOUGHT_COLLAPSED_LINE_COUNT;
  const hiddenLineCount = contentLines.length - THOUGHT_COLLAPSED_LINE_COUNT;
  const displayedContent =
    showAllLines || !isLineCollapsible
      ? content
      : contentLines.slice(0, THOUGHT_COLLAPSED_LINE_COUNT).join("\n");

  return (
    <View className="px-4 py-0.5">
      <Pressable
        onPress={() => {
          if (!hasContent) return;
          setExpanded((v) => !v);
          if (!expanded) setShowAllLines(false);
        }}
        className="flex-row items-center gap-2"
      >
        <Brain size={12} color={themeColors.gray[11]} />
        <Text className="text-[13px] text-gray-11">Thinking</Text>
      </Pressable>
      {expanded && hasContent && (
        <View className="mt-1 ml-5 overflow-hidden rounded-lg border border-gray-6 px-3 py-2">
          <Text
            className="font-mono text-[12px] text-gray-11 leading-4"
            selectable
          >
            {displayedContent}
          </Text>
          {isLineCollapsible && !showAllLines && (
            <Pressable
              onPress={() => setShowAllLines(true)}
              className="mt-1 self-start"
              hitSlop={6}
            >
              <Text className="text-[12px] text-gray-10">
                +{hiddenLineCount} more lines
              </Text>
            </Pressable>
          )}
        </View>
      )}
    </View>
  );
}

// Detect objects like {"0":"E","1":"r","2":"r",...,"isError":true} — a string
// serialized as char-per-key (possibly with extra metadata keys mixed in).
function tryReassembleString(obj: Record<string, unknown>): string | null {
  const numericKeys = Object.keys(obj).filter((k) => /^\d+$/.test(k));
  if (numericKeys.length < 3) return null;
  if (
    numericKeys.every(
      (k) => typeof obj[k] === "string" && (obj[k] as string).length === 1,
    )
  ) {
    return numericKeys
      .sort((a, b) => Number(a) - Number(b))
      .map((k) => obj[k])
      .join("");
  }
  return null;
}

function extractErrorText(result: unknown): string | null {
  if (typeof result === "string") return result;
  if (Array.isArray(result)) {
    const texts = result.map(extractErrorText).filter(Boolean);
    return texts.length > 0 ? texts.join("\n") : null;
  }
  if (!result || typeof result !== "object") return null;
  const obj = result as Record<string, unknown>;

  // Reassemble char-per-key strings: {"0":"E","1":"r",...}
  const reassembled = tryReassembleString(obj);
  if (reassembled) return reassembled;

  // Check simple string fields, recurse into nested objects
  for (const key of [
    "error",
    "message",
    "stderr",
    "output",
    "text",
    "content",
  ]) {
    if (typeof obj[key] === "string") return obj[key] as string;
    if (obj[key] && typeof obj[key] === "object") {
      const nested = extractErrorText(obj[key]);
      if (nested) return nested;
    }
  }

  // Last resort: stringify the result so *something* shows
  try {
    const str = JSON.stringify(result, null, 2);
    if (str && str !== "{}") return str;
  } catch {
    // ignore
  }

  return null;
}

function agentPromptSummary(args?: Record<string, unknown>): string | null {
  if (!args) return null;
  const prompt =
    typeof args.prompt === "string"
      ? args.prompt
      : typeof args.description === "string"
        ? args.description
        : null;
  if (!prompt) return null;
  // Take the first meaningful line, truncated
  const firstLine = prompt
    .split("\n")
    .find((l) => l.trim())
    ?.trim();
  if (!firstLine) return null;
  return firstLine.length > 120 ? `${firstLine.slice(0, 120)}…` : firstLine;
}

function AgentToolCard({
  item,
  onOpenTask,
}: {
  item: ParsedMessage;
  onOpenTask?: (taskId: string) => void;
}) {
  const themeColors = useThemeColors();
  const [expanded, setExpanded] = useState(false);
  const toolData = item.toolData;
  const children = item.children ?? [];
  if (!toolData) return null;

  const isLoading =
    toolData.status === "pending" || toolData.status === "running";
  const isFailed = toolData.status === "error";
  const childCount = children.length;
  const subtitle = agentPromptSummary(toolData.args);
  const errorText = isFailed ? extractErrorText(toolData.result) : null;

  return (
    <View className="mx-4 my-1 overflow-hidden rounded-lg border border-gray-6 bg-gray-2">
      {/* Header */}
      <Pressable onPress={() => setExpanded(!expanded)} className="px-3 py-2">
        <View className="flex-row items-center gap-2">
          {isLoading ? (
            <ActivityIndicator size={12} color={themeColors.accent[9]} />
          ) : (
            <Robot
              size={14}
              color={
                isFailed ? themeColors.status.error : themeColors.accent[9]
              }
            />
          )}
          <Text
            className="flex-1 font-mono text-[13px] text-gray-12"
            numberOfLines={1}
          >
            {toolData.toolName}
          </Text>
          {childCount > 0 && (
            <Text className="font-mono text-[11px] text-gray-9">
              {childCount} {childCount === 1 ? "tool" : "tools"}
            </Text>
          )}
          {isFailed && (
            <Text className="font-mono text-[11px] text-status-error">
              Failed
            </Text>
          )}
          <CaretRight
            size={12}
            color={themeColors.gray[9]}
            style={{
              transform: [{ rotate: expanded ? "90deg" : "0deg" }],
            }}
          />
        </View>
        {subtitle && (
          <Text
            className="mt-1 ml-5 text-[12px] text-gray-9 leading-4"
            numberOfLines={2}
          >
            {subtitle}
          </Text>
        )}
      </Pressable>

      {/* Error message + nested tool calls */}
      {expanded && (
        <View className="border-gray-6 border-t">
          {errorText && (
            <View className="mx-3 my-2 rounded bg-status-error/10 px-3 py-2">
              <Text
                className="font-mono text-[12px] text-status-error leading-4"
                selectable
              >
                {errorText}
              </Text>
            </View>
          )}
          {children.map((child) => {
            if (!child.toolData) return null;
            return (
              <ToolMessage
                key={child.id}
                toolName={child.toolData.toolName}
                rawToolName={child.toolData.rawToolName}
                kind={deriveToolKind(
                  child.toolData.rawToolName ?? child.toolData.toolName,
                )}
                status={child.toolData.status}
                args={child.toolData.args}
                result={child.toolData.result}
                onOpenTask={onOpenTask}
              />
            );
          })}
        </View>
      )}
    </View>
  );
}

function formatElapsed(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

function useElapsedTimer() {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    setElapsed(0);
    const interval = setInterval(() => {
      setElapsed((e) => e + 1);
    }, 1000);
    return () => clearInterval(interval);
  }, []);
  return elapsed;
}

function ThinkingIndicator() {
  const [dots, setDots] = useState(1);
  const [activity, setActivity] = useState(getRandomThinkingActivity);
  const elapsed = useElapsedTimer();
  const themeColors = useThemeColors();

  useEffect(() => {
    const interval = setInterval(() => {
      setDots((d) => (d % 3) + 1);
    }, 500);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    const interval = setInterval(() => {
      setActivity(getRandomThinkingActivity());
    }, 2000);
    return () => clearInterval(interval);
  }, []);

  return (
    <View className="px-4 py-0.5">
      <View className="flex-row items-center justify-between">
        <View className="flex-row items-center gap-2">
          <Brain size={12} color={themeColors.gray[8]} />
          <Text className="font-mono text-[12px] text-gray-8">
            {activity}
            {".".repeat(dots)}
          </Text>
        </View>
        <Text className="font-mono text-[12px] text-gray-8">
          {formatElapsed(elapsed)}
        </Text>
      </View>
    </View>
  );
}

function ConnectingIndicator() {
  const [dots, setDots] = useState(1);
  const elapsed = useElapsedTimer();
  const themeColors = useThemeColors();

  useEffect(() => {
    const interval = setInterval(() => {
      setDots((d) => (d % 3) + 1);
    }, 500);
    return () => clearInterval(interval);
  }, []);

  return (
    <View className="px-4 py-0.5">
      <View className="flex-row items-center justify-between">
        <View className="flex-row items-center gap-2">
          <CloudArrowDown size={12} color={themeColors.gray[8]} />
          <Text className="font-mono text-[12px] text-gray-8">
            Connecting{".".repeat(dots)}
          </Text>
        </View>
        <Text className="font-mono text-[12px] text-gray-8">
          {formatElapsed(elapsed)}
        </Text>
      </View>
    </View>
  );
}

export function TaskSessionView({
  events,
  taskId,
  pendingPermissions,
  isConnecting,
  isThinking,
  terminalStatus,
  lastError,
  onRetry,
  onOpenTask,
  onSendPermissionResponse,
  contentContainerStyle,
  optimisticUserMessage,
}: TaskSessionViewProps) {
  const processorRef = useRef(createProcessorState());
  const prevEventsRef = useRef(events);
  // Reset processor when events array shrinks or changes identity completely
  // (e.g., navigating between tasks while Expo Router reuses the component).
  if (
    events.length === 0 ||
    (events !== prevEventsRef.current && events[0] !== prevEventsRef.current[0])
  ) {
    processorRef.current = createProcessorState();
  }
  prevEventsRef.current = events;
  const { messages, plan } = useMemo(
    () => processNewEvents(processorRef.current, events),
    [events],
  );

  // When the agent stops (cancel, completion, terminal), sweep any
  // tools still stuck in pending/running to "completed" so their
  // spinners stop.
  const agentActive = isConnecting || isThinking;
  const prevAgentActive = useRef(agentActive);
  if (prevAgentActive.current && !agentActive) {
    const state = processorRef.current;
    let swept = false;
    for (const msg of state.toolMessages.values()) {
      const permission = msg.toolData
        ? pendingPermissions?.[msg.toolData.toolCallId]
        : undefined;
      if (
        msg.toolData &&
        (msg.toolData.status === "pending" ||
          msg.toolData.status === "running") &&
        !isInteractivePermissionTool(msg.toolData, permission)
      ) {
        msg.toolData.status = "completed";
        swept = true;
      }
    }
    if (swept) {
      state.lastSnapshot = [...state.messages];
      state.lastSnapshotLength = state.messages.length;
    }
  }
  prevAgentActive.current = agentActive;

  // Append the optimistic user echo (if any) as the newest message, unless a
  // real `user` message with matching text *and a ts at or after submit time*
  // has already arrived via SSE. Gating on `ts` prevents a text-identical
  // historical turn from suppressing a freshly-submitted echo.
  const messagesWithOptimistic = useMemo(() => {
    if (!optimisticUserMessage) return messages;
    const alreadyEchoed = messages.some(
      (m) =>
        m.type === "user" &&
        m.content === optimisticUserMessage.text &&
        (m.ts ?? 0) >= optimisticUserMessage.setAt,
    );
    if (alreadyEchoed) return messages;
    const optimistic: ParsedMessage = {
      id: "optimistic-user",
      type: "user",
      content: optimisticUserMessage.text,
      attachments: optimisticUserMessage.attachments,
    };
    return [...messages, optimistic];
  }, [messages, optimisticUserMessage]);

  // Inverted FlatList renders data[0] at the visual bottom.
  // Reverse so newest messages are at index 0 = bottom.
  const reversedMessages = useMemo(
    () => [...messagesWithOptimistic].reverse(),
    [messagesWithOptimistic],
  );
  const themeColors = useThemeColors();
  const flatListRef = useRef<FlatList>(null);
  const hasPendingQuestion = useMemo(
    () => messages.some(hasPendingQuestionMessage),
    [messages],
  );
  const showActivityIndicator = agentActive && !hasPendingQuestion;
  const effectiveContentContainerStyle = useMemo(() => {
    const baseStyle = (contentContainerStyle ?? {}) as {
      paddingTop?: number;
      [key: string]: unknown;
    };

    if (!showActivityIndicator) {
      return baseStyle;
    }

    return {
      ...baseStyle,
      // In the inverted list, paddingTop becomes visual bottom spacing.
      // Reserve enough room so the floating activity indicator never
      // covers the last visible row while the agent is working.
      // 28pt was tight at default text sizes and let cards (e.g. the
      // Agent loading card) peek into the indicator strip — 44pt gives
      // a real buffer plus headroom for larger dynamic-type settings.
      paddingTop: (baseStyle.paddingTop ?? 0) + 44,
    };
  }, [contentContainerStyle, showActivityIndicator]);
  // Inverted FlatList: scrollY is the distance from the visual bottom, so
  // any non-trivial value means the user has scrolled up from the latest
  // message. Use a small threshold to ignore iOS bounce.
  const [scrolledFromBottom, setScrolledFromBottom] = useState(false);

  const scrollToBottom = useCallback(() => {
    // Optimistically hide the button — the scroll animation will fire
    // onScroll events too, but the throttle can leave the button visible
    // for a beat after tap if we rely on those alone.
    setScrolledFromBottom(false);
    flatListRef.current?.scrollToOffset({ offset: 0, animated: true });
  }, []);

  const handleScroll = useCallback(
    (e: { nativeEvent: { contentOffset: { y: number } } }) => {
      setScrolledFromBottom(e.nativeEvent.contentOffset.y > 100);
    },
    [],
  );

  const renderAttachment = useCallback(
    (attachment: SessionNotificationAttachment) => (
      <CloudMessageAttachment attachment={attachment} taskId={taskId} />
    ),
    [taskId],
  );

  const renderMessage = useCallback(
    ({ item }: { item: ParsedMessage }) => {
      switch (item.type) {
        case "user":
          return (
            <HumanMessage
              content={item.content}
              timestamp={item.ts}
              attachments={item.attachments}
              renderAttachment={renderAttachment}
            />
          );
        case "agent":
          return (
            <AgentMessage
              content={item.content}
              onOpenTask={onOpenTask}
              timestamp={item.ts}
            />
          );
        case "thought":
          return <CollapsedThought content={item.content} />;
        case "tool":
          if (!item.toolData) return null;
          if (
            isPlanApprovalTool(
              item.toolData,
              pendingPermissions?.[item.toolData.toolCallId],
            )
          ) {
            return (
              <PlanApprovalCard
                toolData={item.toolData}
                permission={pendingPermissions?.[item.toolData.toolCallId]}
                onSendPermissionResponse={onSendPermissionResponse}
              />
            );
          }
          if (isQuestionTool(item.toolData)) {
            return (
              <QuestionCard
                toolData={item.toolData}
                onSendPermissionResponse={onSendPermissionResponse}
              />
            );
          }
          if (item.toolData.isAgent) {
            return <AgentToolCard item={item} onOpenTask={onOpenTask} />;
          }
          return (
            <ToolMessage
              toolName={item.toolData.toolName}
              rawToolName={item.toolData.rawToolName}
              kind={deriveToolKind(
                item.toolData.rawToolName ?? item.toolData.toolName,
              )}
              status={item.toolData.status}
              args={item.toolData.args}
              result={item.toolData.result}
              onOpenTask={onOpenTask}
            />
          );
        default:
          return null;
      }
    },
    [
      onOpenTask,
      onSendPermissionResponse,
      pendingPermissions,
      renderAttachment,
    ],
  );

  return (
    <View className="flex-1">
      <PlanStatusBar plan={plan} />
      <FlatList
        ref={flatListRef}
        data={reversedMessages}
        renderItem={renderMessage}
        keyExtractor={(item) => item.id}
        inverted
        contentContainerStyle={effectiveContentContainerStyle}
        keyboardDismissMode="interactive"
        keyboardShouldPersistTaps="handled"
        showsVerticalScrollIndicator
        onScroll={handleScroll}
        scrollEventThrottle={100}
        maxToRenderPerBatch={15}
        windowSize={21}
        initialNumToRender={30}
        ListHeaderComponent={
          terminalStatus ? (
            <TerminalStatusBanner
              terminalStatus={terminalStatus}
              lastError={lastError}
              onRetry={onRetry}
            />
          ) : null
        }
      />
      {/* Thinking/connecting indicators pinned to the bottom of the list area.
          The Composer is a sibling below TaskSessionView in flex flow, so
          `bottom-0` here sits the strip right above the composer's top edge.
          Solid bg so list rows scrolling under it are occluded instead of
          bleeding through. */}
      {showActivityIndicator && (
        <View className="absolute inset-x-0 bottom-0 bg-background pt-1 pb-2">
          {isConnecting ? (
            <ConnectingIndicator />
          ) : isThinking ? (
            <ThinkingIndicator />
          ) : null}
        </View>
      )}
      {scrolledFromBottom && (
        <Pressable
          onPress={scrollToBottom}
          className="absolute right-4 bottom-4 h-10 w-10 items-center justify-center rounded-full bg-gray-3"
          style={{
            shadowColor: "#000",
            shadowOffset: { width: 0, height: 2 },
            shadowOpacity: 0.2,
            shadowRadius: 4,
            elevation: 4,
          }}
        >
          <ArrowDown size={18} color={themeColors.gray[11]} />
        </Pressable>
      )}
    </View>
  );
}
