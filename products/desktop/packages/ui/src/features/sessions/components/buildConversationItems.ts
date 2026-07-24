import type {
  ContentBlock,
  SessionNotification,
} from "@agentclientprotocol/sdk";
import {
  isNotification,
  POSTHOG_NOTIFICATIONS,
} from "@posthog/agent/acp-extensions";
import { extractPromptDisplayContent } from "@posthog/core/sessions/promptContent";
import {
  type AcpMessage,
  type AgentConversationEvent,
  isJsonRpcNotification,
  isJsonRpcRequest,
  isJsonRpcResponse,
  readParentToolCallId,
  type UserShellExecuteParams,
} from "@posthog/shared";
import {
  type GitActionType,
  parseGitActionMessage,
} from "@posthog/ui/features/sessions/components/GitActionMessage";
import type { UserShellExecute } from "@posthog/ui/features/sessions/components/session-update/UserShellExecuteView";
import type {
  CompactBoundaryMetadata,
  ConversationSessionUpdate,
  ToolCall,
} from "@posthog/ui/features/sessions/types";
import type { UserMessageAttachment } from "@posthog/ui/features/sessions/userMessageTypes";
import {
  extractSkillButtonId,
  type SkillButtonId,
} from "@posthog/ui/features/skill-buttons/prompts";
import type { Step, StepStatus } from "@posthog/ui/primitives/StepList";
import type { RenderItem } from "./session-update/SessionUpdateView";

export interface TurnContext {
  toolCalls: Map<string, ToolCall>;
  childItems: Map<string, ConversationItem[]>;
  turnCancelled: boolean;
  turnComplete: boolean;
}

export type ConversationItem =
  | {
      type: "user_message";
      id: string;
      content: string;
      timestamp: number;
      attachments?: UserMessageAttachment[];
      pinToTop?: boolean;
    }
  | { type: "git_action"; id: string; actionType: GitActionType }
  | { type: "skill_button_action"; id: string; buttonId: SkillButtonId }
  | {
      type: "session_update";
      id: string;
      update: RenderItem;
      turnContext: TurnContext;
      thoughtComplete?: boolean;
      timestamp?: number;
    }
  | {
      type: "git_action_result";
      id: string;
      actionType: GitActionType;
      turnId: string;
    }
  | { type: "turn_cancelled"; id: string; interruptReason?: string }
  | UserShellExecute;

export interface LastTurnInfo {
  isComplete: boolean;
  durationMs: number;
  stopReason?: string;
}

export interface BuildResult {
  items: ConversationItem[];
  lastTurnInfo: LastTurnInfo | null;
  isCompacting: boolean;
  /** Number of tool calls settled into a terminal status so far. Monotonic
   *  within a thread; consumers treat a change as "a tool/MCP call finished". */
  completedToolCallCount: number;
}

interface ProgressCardState {
  /** Step key → full step entry. Key order reflects arrival order. */
  steps: Map<string, Step>;
  /** Reference to the pushed render item; mutated in place as events arrive. */
  renderItem: {
    sessionUpdate: "progress_group";
    steps: Step[];
    isActive: boolean;
  };
  /** Index in `items` where this card sits. */
  itemIndex: number;
  /** Run id parsed from the `group` (`setup:<runId>`); empty if absent. */
  runId: string;
}

interface TurnState {
  id: string;
  promptId: number | string;
  isComplete: boolean;
  stopReason?: string;
  interruptReason?: string;
  durationMs: number;
  toolCalls: Map<string, ToolCall>;
  context: TurnContext;
  gitAction: ReturnType<typeof parseGitActionMessage>;
  itemCount: number;
}

export interface ItemBuilder {
  items: ConversationItem[];
  currentTurn: TurnState | null;
  /** Index in `items` where the current turn's first item sits. Lets an
   *  incremental consumer treat everything before it (completed turns) as
   *  frozen and only re-derive the active turn. */
  currentTurnStartIndex: number;
  pendingPrompts: Map<number | string, TurnState>;
  shellExecutes: Map<string, { item: UserShellExecute; index: number }>;
  isCompacting: boolean;
  nextId: () => number;
  /** Progress cards keyed by the backend-supplied `group` id. The first event
   *  for a group opens the card inline where it arrived; every subsequent
   *  event for the same id mutates the same card, regardless of which turn is
   *  currently active. */
  progressCards: Map<string, ProgressCardState>;
  /** Lowest item index touched by a progress event since it was last reset.
   *  An incremental consumer resets this before feeding a batch of events and
   *  reads it after to detect a card being mutated inside an already frozen
   *  (completed) turn, which would otherwise go unseen. */
  lowestTouchedProgressIndex: number;
  /** Count of tool calls that have reached a terminal status (completed /
   *  failed / cancelled). Increments once per tool call when it first settles.
   *  Drives the generating indicator's status word so it advances on real work
   *  finishing rather than on a timer. */
  completedToolCallCount: number;
  /** Runs that emitted `_posthog/run_started`; until then the setup card's
   *  "agent" step stays in_progress rather than completing at HTTP-boot time. */
  runStartedRunIds: Set<string>;
}

export function createItemBuilder(): ItemBuilder {
  let idCounter = 0;
  return {
    items: [],
    currentTurn: null,
    currentTurnStartIndex: 0,
    pendingPrompts: new Map(),
    shellExecutes: new Map(),
    isCompacting: false,
    nextId: () => idCounter++,
    progressCards: new Map(),
    lowestTouchedProgressIndex: Number.POSITIVE_INFINITY,
    completedToolCallCount: 0,
    runStartedRunIds: new Set(),
  };
}

const TERMINAL_TOOL_STATUSES = new Set(["completed", "failed", "cancelled"]);

function isTerminalToolStatus(status: string | null | undefined): boolean {
  return status != null && TERMINAL_TOOL_STATUSES.has(status);
}

function isThoughtItem(
  item: ConversationItem,
): item is ConversationItem & { type: "session_update" } {
  return (
    item.type === "session_update" &&
    item.update.sessionUpdate === "agent_thought_chunk"
  );
}

export function markThoughtCompletion(items: ConversationItem[]) {
  markThoughtCompletionInItems(items, new Set());
}

function markThoughtCompletionInItems(
  items: ConversationItem[],
  visited: Set<ConversationItem[]>,
) {
  if (visited.has(items)) return;
  visited.add(items);
  const seenContexts = new Set<TurnContext>();
  const itemContexts = new Set<TurnContext>();

  for (let i = items.length - 1; i >= 0; i--) {
    const item = items[i];

    if (isThoughtItem(item)) {
      item.thoughtComplete =
        seenContexts.has(item.turnContext) || item.turnContext.turnComplete;
    }

    if (item.type === "session_update") {
      seenContexts.add(item.turnContext);
      itemContexts.add(item.turnContext);
    }
  }

  for (const context of itemContexts) {
    for (const children of context.childItems.values()) {
      markThoughtCompletionInItems(children, visited);
    }
  }
}

function pushItem(b: ItemBuilder, update: RenderItem, ts?: number) {
  const turn = b.currentTurn;
  if (!turn) return;
  turn.itemCount++;
  b.items.push({
    type: "session_update",
    id: `${turn.id}-item-${b.nextId()}`,
    update,
    turnContext: turn.context,
    timestamp: ts,
  });
}

export interface BuildConversationOptions {
  /** Render `debug`-level console logs inline; without this only info/warn/error show up. */
  showDebugLogs?: boolean;
}

export function buildConversationItems(
  events: AcpMessage[],
  isPromptPending: boolean | null,
  options?: BuildConversationOptions,
): BuildResult {
  const b = createItemBuilder();

  let ordered = events;
  for (let i = 1; i < events.length; i++) {
    if (events[i].ts < events[i - 1].ts) {
      ordered = [...events].sort((a, b) => a.ts - b.ts);
      break;
    }
  }
  for (const event of ordered) {
    processEvent(b, event, options);
  }

  finalizeBuilder(b, isPromptPending);

  const lastTurnInfo = readLastTurnInfo(b);

  return {
    items: b.items,
    lastTurnInfo,
    isCompacting: b.isCompacting,
    completedToolCallCount: b.completedToolCallCount,
  };
}

/**
 * Apply one raw event to the builder. This is the append-only core: it never
 * runs end-of-stream finalization, so it is safe to call incrementally as new
 * events arrive without corrupting prior state.
 */
export function processEvent(
  b: ItemBuilder,
  event: AcpMessage,
  options?: BuildConversationOptions,
) {
  const msg = event.message;

  if (isJsonRpcNotification(msg)) {
    handleNotification(b, msg, event.ts, options);
    return;
  }

  if (isJsonRpcRequest(msg) && msg.method === "session/prompt") {
    handlePromptRequest(b, msg, event.ts);
    return;
  }

  if (isJsonRpcResponse(msg) && b.pendingPrompts.has(msg.id)) {
    handlePromptResponse(b, msg, event.ts);
  }
}

/**
 * End-of-stream finalization: speculative completions that assume no further
 * events arrive. Mutates the builder in place, so an incremental consumer must
 * only apply it to a snapshot it is about to read, never to state it will keep
 * feeding events into.
 */
export function buildAgentConversationItems(
  events: AgentConversationEvent[],
  isPromptPending: boolean | null,
): BuildResult {
  const b = createItemBuilder();
  const ordered = [...events].sort(
    (left, right) => left.timestamp - right.timestamp,
  );

  for (const event of ordered) {
    processAgentConversationEvent(b, event);
  }

  finalizeBuilder(b, isPromptPending);

  return {
    items: b.items,
    lastTurnInfo: readLastTurnInfo(b),
    isCompacting: b.isCompacting,
    completedToolCallCount: b.completedToolCallCount,
  };
}

export function processAgentConversationEvent(
  b: ItemBuilder,
  event: AgentConversationEvent,
): void {
  if (event.type === "user_message") {
    handlePromptRequest(
      b,
      { id: event.id, params: { prompt: event.content } },
      event.timestamp,
    );
    return;
  }

  if (event.type === "assistant_message_chunk") {
    processSessionUpdate(
      b,
      { sessionUpdate: "agent_message_chunk", content: event.content },
      event.timestamp,
    );
    return;
  }

  if (event.type === "assistant_thought_chunk") {
    processSessionUpdate(
      b,
      { sessionUpdate: "agent_thought_chunk", content: event.content },
      event.timestamp,
    );
    return;
  }

  if (event.type === "tool_call_started") {
    const { id, parentId, ...toolCall } = event.toolCall;
    const update: ConversationSessionUpdate = {
      sessionUpdate: "tool_call",
      toolCallId: id,
      ...toolCall,
      ...(parentId
        ? { _meta: { claudeCode: { parentToolCallId: parentId } } }
        : {}),
    };
    processSessionUpdate(b, update, event.timestamp);
    return;
  }

  if (event.type === "tool_call_updated") {
    const { id, parentId, ...toolCall } = event.toolCall;
    const update: ConversationSessionUpdate = {
      sessionUpdate: "tool_call_update",
      toolCallId: id,
      ...toolCall,
      ...(parentId
        ? { _meta: { claudeCode: { parentToolCallId: parentId } } }
        : {}),
    };
    processSessionUpdate(b, update, event.timestamp);
    return;
  }

  if (event.type === "runtime_status") {
    handleRuntimeStatus(b, event, event.timestamp);
    return;
  }

  if (event.type === "runtime_error") {
    ensureImplicitTurn(b, event.timestamp);
    const duplicate = b.items
      .slice(b.currentTurnStartIndex)
      .some(
        (item) =>
          item.type === "session_update" &&
          item.update.sessionUpdate === "error" &&
          item.update.errorType === event.errorType &&
          item.update.message === event.message,
      );

    if (!duplicate) {
      pushItem(
        b,
        {
          sessionUpdate: "error",
          errorType: event.errorType,
          message: event.message,
        },
        event.timestamp,
      );
    }
    return;
  }

  if (b.currentTurn) {
    completePromptTurn(b, b.currentTurn, event.timestamp, {
      stopReason: event.stopReason,
    });
  }
}

export function finalizeBuilder(
  b: ItemBuilder,
  isPromptPending: boolean | null,
) {
  // Only mark unresolved prompts as cancelled when we actively track prompt
  // state (local sessions). For cloud sessions isPromptPending is
  // null, meaning that the response hasn't streamed "in" yet
  if (isPromptPending === false) {
    for (const turn of b.pendingPrompts.values()) {
      turn.isComplete = true;
      turn.durationMs = 0;
      turn.context.turnComplete = true;
    }
  }

  // Mark implicit turn complete if it's still the current turn after all events
  if (b.currentTurn?.promptId === -1) {
    b.currentTurn.isComplete = true;
    b.currentTurn.context.turnComplete = true;
  }

  markThoughtCompletion(b.items);
}

export function readLastTurnInfo(b: ItemBuilder): LastTurnInfo | null {
  return b.currentTurn
    ? {
        isComplete: b.currentTurn.isComplete,
        durationMs: b.currentTurn.durationMs,
        stopReason: b.currentTurn.stopReason,
      }
    : null;
}

function handlePromptRequest(
  b: ItemBuilder,
  msg: { id: number | string; params?: unknown },
  ts: number,
) {
  // If the current turn is the implicit one, mark it complete before starting a real turn
  if (b.currentTurn && b.currentTurn.promptId === -1) {
    b.currentTurn.isComplete = true;
    b.currentTurn.context.turnComplete = true;
  }

  const userPrompt = extractUserPrompt(msg.params);
  const userContent = userPrompt.content;

  if (userContent.trim().length === 0 && userPrompt.attachments.length === 0) {
    return;
  }

  const turnId = `turn-${ts}-${msg.id}`;
  const toolCalls = new Map<string, ToolCall>();
  const gitAction = parseGitActionMessage(userContent);
  const skillButtonId = extractSkillButtonId(userPrompt.blocks);

  const childItems = new Map<string, ConversationItem[]>();
  const context: TurnContext = {
    toolCalls,
    childItems,
    turnCancelled: false,
    turnComplete: false,
  };

  // The orchestrator emits its setup progress ("Started agent") before the
  // prompt it responds to is replayed onto the stream, so the card would sit
  // above the user's message. Open the turn before any trailing progress cards
  // so the transcript reads user message → setup → work.
  let insertIndex = b.items.length;
  while (insertIndex > 0) {
    const prev = b.items[insertIndex - 1];
    if (
      prev.type === "session_update" &&
      prev.update.sessionUpdate === "progress_group"
    ) {
      insertIndex--;
    } else {
      break;
    }
  }
  if (insertIndex < b.items.length) {
    for (const card of b.progressCards.values()) {
      if (card.itemIndex >= insertIndex) card.itemIndex++;
    }
    // The shifted cards may live inside a turn the incremental builder already
    // froze; flag the mutation so it falls back to a full rebuild.
    if (insertIndex < b.lowestTouchedProgressIndex) {
      b.lowestTouchedProgressIndex = insertIndex;
    }
  }

  b.currentTurnStartIndex = insertIndex;
  b.currentTurn = {
    id: turnId,
    promptId: msg.id,
    isComplete: false,
    durationMs: -ts,
    toolCalls,
    context,
    gitAction,
    itemCount: 0,
  };

  b.pendingPrompts.set(msg.id, b.currentTurn);

  if (gitAction.isGitAction && gitAction.actionType) {
    b.items.splice(insertIndex, 0, {
      type: "git_action",
      id: `${turnId}-git-action`,
      actionType: gitAction.actionType,
    });
  } else if (skillButtonId) {
    b.items.splice(insertIndex, 0, {
      type: "skill_button_action",
      id: `${turnId}-skill-action`,
      buttonId: skillButtonId,
    });
  } else {
    b.items.splice(insertIndex, 0, {
      type: "user_message",
      id: `${turnId}-user`,
      content: userContent,
      timestamp: ts,
      attachments: userPrompt.attachments,
    });
  }
}

function handlePromptResponse(
  b: ItemBuilder,
  msg: { id: number; result?: unknown },
  ts: number,
) {
  const turn = b.pendingPrompts.get(msg.id);
  if (!turn) return;
  const result = msg.result as {
    stopReason?: string;
    _meta?: { interruptReason?: string };
  };
  completePromptTurn(b, turn, ts, {
    stopReason: result?.stopReason,
    interruptReason: result?._meta?.interruptReason,
  });
}

function completePromptTurn(
  b: ItemBuilder,
  turn: TurnState,
  ts: number,
  result: { stopReason?: string; interruptReason?: string } = {},
) {
  if (turn.isComplete) return;

  turn.isComplete = true;
  turn.durationMs += ts;

  turn.stopReason = result?.stopReason;
  turn.interruptReason = result?.interruptReason;
  turn.context.turnComplete = true;

  const wasCancelled = turn.stopReason === "cancelled";
  turn.context.turnCancelled = wasCancelled;

  if (turn.gitAction.isGitAction && turn.gitAction.actionType) {
    b.items.push({
      type: "git_action_result",
      id: `${turn.id}-git-result`,
      actionType: turn.gitAction.actionType,
      turnId: turn.id,
    });
  }

  if (wasCancelled) {
    b.items.push({
      type: "turn_cancelled",
      id: `${turn.id}-cancelled`,
      interruptReason: turn.interruptReason,
    });
  }

  if (turn.promptId !== -1) {
    b.pendingPrompts.delete(turn.promptId);
  }
}

function handleNotification(
  b: ItemBuilder,
  msg: { method: string; params?: unknown },
  ts: number,
  options?: BuildConversationOptions,
) {
  if (msg.method === "_array/user_shell_execute") {
    const params = msg.params as UserShellExecuteParams;
    const existing = b.shellExecutes.get(params.id);
    if (existing) {
      existing.item.result = params.result;
    } else {
      const item: UserShellExecute = {
        type: "user_shell_execute",
        id: params.id,
        command: params.command,
        cwd: params.cwd,
        result: params.result,
      };
      b.shellExecutes.set(params.id, { item, index: b.items.length });
      b.items.push(item);
    }
    return;
  }

  if (msg.method === "session/update") {
    const update = (msg.params as SessionNotification)?.update;
    if (!update) return;
    processSessionUpdate(b, update, ts);
    return;
  }

  // `_posthog/resources_used` is intentionally NOT rendered inline here — the
  // products are surfaced as a persistent, de-duplicated bar above the composer
  // (see accumulateSessionResources / SessionResourcesBar).

  if (
    isNotification(msg.method, POSTHOG_NOTIFICATIONS.TURN_COMPLETE) ||
    isNotification(msg.method, POSTHOG_NOTIFICATIONS.BACKGROUND_TURN_COMPLETE)
  ) {
    const params = msg.params as { stopReason?: string } | undefined;
    if (!b.currentTurn) return;
    completePromptTurn(b, b.currentTurn, ts, {
      stopReason: params?.stopReason,
    });
    return;
  }

  if (isNotification(msg.method, POSTHOG_NOTIFICATIONS.CONSOLE)) {
    const params = msg.params as { level?: string; message?: string };
    if (!params?.message) return;
    const level = params.level ?? "info";
    if (level === "debug" && !options?.showDebugLogs) return;
    ensureImplicitTurn(b, ts);
    pushItem(b, {
      sessionUpdate: "console",
      level,
      message: params.message,
      timestamp: new Date(ts).toISOString(),
    });
    return;
  }

  if (isNotification(msg.method, POSTHOG_NOTIFICATIONS.PROGRESS)) {
    handleProgress(b, msg.params, ts);
    return;
  }

  if (isNotification(msg.method, POSTHOG_NOTIFICATIONS.RUN_STARTED)) {
    const runId = (msg.params as { runId?: string } | undefined)?.runId;
    if (runId) {
      b.runStartedRunIds.add(runId);
      const card = b.progressCards.get(`setup:${runId}`);
      if (card) {
        if (card.itemIndex < b.lowestTouchedProgressIndex) {
          b.lowestTouchedProgressIndex = card.itemIndex;
        }
        syncProgressCard(card, b);
      }
    }
    return;
  }

  if (isNotification(msg.method, POSTHOG_NOTIFICATIONS.COMPACT_BOUNDARY)) {
    ensureImplicitTurn(b, ts);
    const params = msg.params as CompactBoundaryMetadata;
    markRuntimeStatusComplete(b, "compacting");
    pushItem(b, {
      sessionUpdate: "compact_boundary",
      trigger: params.trigger,
      preTokens: params.preTokens,
      contextSize: params.contextSize,
    });
    return;
  }

  if (isNotification(msg.method, POSTHOG_NOTIFICATIONS.STATUS)) {
    ensureImplicitTurn(b, ts);
    const params = msg.params as {
      status: string;
      isComplete?: boolean;
      error?: string;
      explanation?: string;
      fromModel?: string;
      toModel?: string;
    };
    handleRuntimeStatus(b, params, ts);
    return;
  }
}

function handleRuntimeStatus(
  b: ItemBuilder,
  status: {
    status: string;
    isComplete?: boolean;
    error?: string;
    explanation?: string;
    fromModel?: string;
    toModel?: string;
    message?: string;
    attempt?: number;
    maxAttempts?: number;
    delayMs?: number;
  },
  timestamp: number,
): void {
  ensureImplicitTurn(b, timestamp);

  if (status.status === "refusal" || status.status === "refusal_fallback") {
    pushItem(b, {
      sessionUpdate: "status",
      status: status.status,
      explanation: status.explanation,
      fromModel: status.fromModel,
      toModel: status.toModel,
    });
    return;
  }

  if (status.status === "compacting") {
    if (status.isComplete) {
      markRuntimeStatusComplete(b, "compacting");
      return;
    }
    b.isCompacting = true;
  } else if (status.status === "compacting_failed") {
    markRuntimeStatusComplete(b, "compacting");
    pushItem(b, {
      sessionUpdate: "status",
      status: "compacting_failed",
      error: status.error,
    });
    return;
  } else if (status.status === "retrying" && status.isComplete) {
    markRuntimeStatusComplete(b, "retrying");
    return;
  }

  pushItem(b, {
    sessionUpdate: "status",
    status: status.status,
    isComplete: status.isComplete,
    startedAt: timestamp,
    message: status.message,
    attempt: status.attempt,
    maxAttempts: status.maxAttempts,
    delayMs: status.delayMs,
  });
}

function ensureProgressCardForGroup(
  b: ItemBuilder,
  group: string,
  ts: number,
): ProgressCardState | null {
  const existing = b.progressCards.get(group);
  if (existing) return existing;

  ensureImplicitTurn(b, ts);
  if (!b.currentTurn) return null;

  const renderItem = {
    sessionUpdate: "progress_group" as const,
    steps: [] as Step[],
    isActive: true,
  };
  const colon = group.indexOf(":");
  const card: ProgressCardState = {
    steps: new Map(),
    renderItem,
    itemIndex: b.items.length,
    runId: colon >= 0 ? group.slice(colon + 1) : "",
  };
  b.progressCards.set(group, card);
  pushItem(b, renderItem);
  return card;
}

function syncProgressCard(card: ProgressCardState, b: ItemBuilder) {
  const gateAgentStep =
    card.runId !== "" && !b.runStartedRunIds.has(card.runId);
  const ordered: Step[] = Array.from(card.steps.values()).map((step) =>
    step.key === "agent" && step.status === "completed" && gateAgentStep
      ? { ...step, status: "in_progress" as StepStatus }
      : step,
  );
  card.renderItem.steps = ordered;
  card.renderItem.isActive = ordered.some((s) => s.status === "in_progress");
}

function handleProgress(b: ItemBuilder, rawParams: unknown, ts: number) {
  const params = rawParams as
    | {
        step?: string;
        status?: string;
        label?: string;
        detail?: string;
        group?: string;
      }
    | undefined;
  if (!params?.step || !params.label || !params.group) return;

  const status = normalizeStepStatus(params.status);
  const card = ensureProgressCardForGroup(b, params.group, ts);
  if (!card) return;
  if (card.itemIndex < b.lowestTouchedProgressIndex) {
    b.lowestTouchedProgressIndex = card.itemIndex;
  }
  card.steps.set(params.step, {
    key: params.step,
    status,
    label: params.label,
    detail: params.detail,
  });
  syncProgressCard(card, b);
}

function normalizeStepStatus(raw: string | undefined): StepStatus {
  switch (raw) {
    case "in_progress":
    case "completed":
    case "failed":
      return raw;
    default:
      return "in_progress";
  }
}

function markRuntimeStatusComplete(b: ItemBuilder, status: string) {
  if (status === "compacting") {
    b.isCompacting = false;
  }
  for (let i = b.items.length - 1; i >= 0; i--) {
    const item = b.items[i];
    if (
      item.type === "session_update" &&
      item.update.sessionUpdate === "status" &&
      item.update.status === status &&
      !item.update.isComplete
    ) {
      // Replace the row and its update with fresh objects rather than mutating
      // in place. The incremental builder reuses item identity so memoized rows
      // skip re-render; an in-place flip can be missed, leaving the finished row
      // stuck with its spinner and a still-ticking timer. A new reference forces
      // the completion to render (and the row to unmount).
      b.items[i] = { ...item, update: { ...item.update, isComplete: true } };
      return;
    }
  }
}

function ensureImplicitTurn(b: ItemBuilder, ts: number) {
  if (b.currentTurn && !b.currentTurn.isComplete) return;

  b.currentTurnStartIndex = b.items.length;
  const turnId = `turn-${ts}-implicit`;
  const toolCalls = new Map<string, ToolCall>();
  const childItems = new Map<string, ConversationItem[]>();
  const context: TurnContext = {
    toolCalls,
    childItems,
    turnCancelled: false,
    turnComplete: false,
  };

  b.currentTurn = {
    id: turnId,
    promptId: -1,
    isComplete: false,
    durationMs: -ts,
    toolCalls,
    context,
    gitAction: { isGitAction: false, actionType: null, prompt: "" },
    itemCount: 0,
  };
}

function extractUserPrompt(params: unknown): {
  content: string;
  attachments: UserMessageAttachment[];
  blocks: ContentBlock[];
} {
  const p = params as { prompt?: ContentBlock[] };
  if (!p?.prompt?.length) {
    return { content: "", attachments: [], blocks: [] };
  }

  const { text, attachments } = extractPromptDisplayContent(p.prompt, {
    filterHidden: true,
  });
  return { content: text, attachments, blocks: p.prompt };
}

function getParentToolCallId(
  update: ConversationSessionUpdate,
): string | undefined {
  return readParentToolCallId((update as Record<string, unknown>)._meta);
}

function pushChildItem(b: ItemBuilder, parentId: string, update: RenderItem) {
  const turn = b.currentTurn;
  if (!turn) return;
  let children = turn.context.childItems.get(parentId);
  if (!children) {
    children = [];
    turn.context.childItems.set(parentId, children);
  }
  turn.itemCount++;
  children.push({
    type: "session_update",
    id: `${turn.id}-child-${b.nextId()}`,
    update,
    turnContext: turn.context,
  });
}

function appendTextChunkToChildren(
  b: ItemBuilder,
  parentId: string,
  update: ConversationSessionUpdate & {
    sessionUpdate: "agent_message_chunk" | "agent_thought_chunk";
  },
) {
  if (update.content.type !== "text") return;
  const turn = b.currentTurn;
  if (!turn) return;
  let children = turn.context.childItems.get(parentId);
  if (!children) {
    children = [];
    turn.context.childItems.set(parentId, children);
  }

  const lastChild = children[children.length - 1];
  if (
    lastChild?.type === "session_update" &&
    lastChild.update.sessionUpdate === update.sessionUpdate &&
    "content" in lastChild.update &&
    lastChild.update.content.type === "text"
  ) {
    const prevText = (
      lastChild.update.content as { type: "text"; text: string }
    ).text;
    children[children.length - 1] = {
      ...lastChild,
      update: {
        ...lastChild.update,
        content: {
          type: "text",
          text: prevText + update.content.text,
        },
      },
    };
  } else {
    turn.itemCount++;
    children.push({
      type: "session_update",
      id: `${turn.id}-child-${b.nextId()}`,
      update: { ...update, content: { ...update.content } },
      turnContext: turn.context,
    });
  }
}

function processSessionUpdate(
  b: ItemBuilder,
  update: ConversationSessionUpdate,
  ts: number,
) {
  switch (update.sessionUpdate) {
    case "user_message_chunk":
      break;

    case "agent_message_chunk":
    case "agent_thought_chunk": {
      if (update.content.type !== "text") break;
      const parentId = getParentToolCallId(update);
      if (parentId) {
        appendTextChunkToChildren(b, parentId, update);
      } else {
        ensureImplicitTurn(b, ts);
        appendTextChunk(b, update, ts);
      }
      break;
    }

    case "tool_call": {
      ensureImplicitTurn(b, ts);
      const turn = b.currentTurn;
      if (!turn) break;
      const existing = turn.toolCalls.get(update.toolCallId);
      if (existing) {
        const wasTerminal = isTerminalToolStatus(existing.status);
        Object.assign(existing, update);
        if (!wasTerminal && isTerminalToolStatus(existing.status)) {
          b.completedToolCallCount++;
        }
      } else {
        const toolCall = { ...update };
        turn.toolCalls.set(update.toolCallId, toolCall);
        if (isTerminalToolStatus(toolCall.status)) {
          b.completedToolCallCount++;
        }
        const parentId = getParentToolCallId(update);
        if (parentId) {
          pushChildItem(b, parentId, toolCall);
        } else {
          pushItem(b, toolCall, ts);
        }
      }
      break;
    }

    case "tool_call_update": {
      const turn = b.currentTurn;
      if (!turn) break;
      const existing = turn.toolCalls.get(update.toolCallId);
      if (existing) {
        const wasTerminal = isTerminalToolStatus(existing.status);
        const { sessionUpdate: _, ...rest } = update;
        Object.assign(existing, rest);
        if (!wasTerminal && isTerminalToolStatus(existing.status)) {
          b.completedToolCallCount++;
        }
      }
      break;
    }

    case "plan":
    case "available_commands_update":
    case "config_option_update":
    case "usage_update":
      break;

    default: {
      const customUpdate = update as unknown as {
        sessionUpdate: string;
        content?: { type: string; text?: string };
        status?: string;
        errorType?: string;
        message?: string;
      };
      if (customUpdate.sessionUpdate === "agent_message") {
        if (customUpdate.content?.type === "text") {
          ensureImplicitTurn(b, ts);
          appendTextChunk(
            b,
            {
              sessionUpdate: "agent_message_chunk" as const,
              content: customUpdate.content as { type: "text"; text: string },
            },
            ts,
          );
        }
      } else if (
        customUpdate.sessionUpdate === "status" ||
        customUpdate.sessionUpdate === "error"
      ) {
        ensureImplicitTurn(b, ts);
        pushItem(b, customUpdate as unknown as RenderItem, ts);
      }
      break;
    }
  }
}

function appendTextChunk(
  b: ItemBuilder,
  update: ConversationSessionUpdate & {
    sessionUpdate: "agent_message_chunk" | "agent_thought_chunk";
  },
  ts: number,
) {
  if (update.content.type !== "text") return;

  const lastItem = b.items[b.items.length - 1];
  if (
    lastItem?.type === "session_update" &&
    lastItem.turnContext === b.currentTurn?.context &&
    lastItem.update.sessionUpdate === update.sessionUpdate &&
    "content" in lastItem.update &&
    lastItem.update.content.type === "text"
  ) {
    b.items[b.items.length - 1] = {
      ...lastItem,
      update: {
        ...lastItem.update,
        content: {
          type: "text",
          text: lastItem.update.content.text + update.content.text,
        },
      },
    };
  } else {
    pushItem(b, { ...update, content: { ...update.content } }, ts);
  }
}
