import type {
  ContentBlock,
  SessionNotification,
} from "@agentclientprotocol/sdk";
import {
  isNotification,
  POSTHOG_NOTIFICATIONS,
} from "@posthog/agent/acp-extensions";
import { extractPromptDisplayContent } from "@posthog/core/sessions/promptContent";
import { isSteerPromptParams } from "@posthog/core/sessions/sessionEvents";
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
  /** A `/clear` is in flight (its status row shows the dedicated spinner), so
   *  the generic "Generating…" footer must stay hidden — same as compaction. */
  isClearing: boolean;
  /** Number of tool calls settled into a terminal status so far. Monotonic
   *  within a thread; consumers treat a change as "a tool/MCP call finished". */
  completedToolCallCount: number;
  /** Timestamp (ms) of the most recent event applied to the thread, or null
   *  when none have been. Lets the footer say how long the agent has been
   *  silent: a turn can sit minutes inside one tool call or thinking block
   *  with nothing new to render, and a frozen status word reads as a hang. */
  lastActivityAt: number | null;
  /** A background turn started without a prompt RPC and has not completed. */
  isBackgroundTurnActive: boolean;
}

interface ProgressCardState {
  /** Step key → full step entry. Key order reflects arrival order. */
  steps: Map<string, Step>;
  /** Replaced when steps change so memoized rows observe live progress. */
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
  /** Per-turn so item ids survive older-history prepends; the virtualized thread anchors on them. */
  nextItemId: number;
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
  isClearing: boolean;
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
  /** Timestamp (ms) of the newest event fed to this builder. See the field of
   *  the same name on `BuildResult`. */
  lastActivityAt: number | null;
  isBackgroundTurnActive: boolean;
  /** Runs that emitted `_posthog/run_started`; until then the setup card's
   *  "agent" step stays in_progress rather than completing at HTTP-boot time. */
  runStartedRunIds: Set<string>;
  /** Plans recovered from `_posthog/permission_request` frames, keyed by
   *  toolCallId. A sandbox agent that read the plan from a plan file sends the
   *  ExitPlanMode tool_call plan-less — the plan travels only inside the
   *  permission request — and the resolving tool_call_update replays the raw
   *  plan-less input, so the plan is re-applied after every merge. */
  recoveredPlans: Map<string, string>;
}

export function createItemBuilder(): ItemBuilder {
  return {
    items: [],
    currentTurn: null,
    currentTurnStartIndex: 0,
    pendingPrompts: new Map(),
    shellExecutes: new Map(),
    isCompacting: false,
    isClearing: false,
    progressCards: new Map(),
    lowestTouchedProgressIndex: Number.POSITIVE_INFINITY,
    completedToolCallCount: 0,
    lastActivityAt: null,
    isBackgroundTurnActive: false,
    runStartedRunIds: new Set(),
    recoveredPlans: new Map(),
  };
}

/** Record that an event landed at `ts`. Events are usually fed in order, but a
 *  rebuild sorts them and an append can carry a stale ts, so keep the max. */
function noteActivity(b: ItemBuilder, ts: number) {
  if (b.lastActivityAt === null || ts > b.lastActivityAt) {
    b.lastActivityAt = ts;
  }
}

const TERMINAL_TOOL_STATUSES = new Set(["completed", "failed", "cancelled"]);

/** The plan markdown carried by an ExitPlanMode-shaped input, or undefined. */
function recoveredPlanOf(rawInput: unknown): string | undefined {
  const plan = (rawInput as { plan?: unknown } | null | undefined)?.plan;
  return typeof plan === "string" && plan.trim() ? plan : undefined;
}

function toolCallCarriesPlan(toolCall: ToolCall): boolean {
  if (recoveredPlanOf(toolCall.rawInput)) return true;
  return (toolCall.content ?? []).some((item) => {
    const record = item as {
      content?: { type?: string; text?: string };
    } | null;
    return record?.content?.type === "text" && !!record.content.text?.trim();
  });
}

/** Fold a recovered plan into `toolCallId`'s call unless it already carries
 *  one (an inline plan always wins). Mutates the registered ToolCall, so an
 *  already-pushed item reflects it. */
function applyRecoveredPlan(b: ItemBuilder, toolCallId: string): void {
  const plan = b.recoveredPlans.get(toolCallId);
  if (!plan) return;
  const toolCall = b.currentTurn?.toolCalls.get(toolCallId);
  if (!toolCall || toolCallCarriesPlan(toolCall)) return;
  toolCall.rawInput = {
    ...(toolCall.rawInput as Record<string, unknown> | null | undefined),
    plan,
  };
}

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
    id: `${turn.id}-item-${turn.nextItemId++}`,
    update,
    turnContext: turn.context,
    timestamp: ts,
  });
}

export interface BuildConversationOptions {
  /** Render `debug`-level console logs inline; without this only info/warn/error show up. */
  showDebugLogs?: boolean;
}

/**
 * The single ordering policy every conversation builder reads events in:
 * ascending timestamp, ties keeping arrival order (`Array.sort` is stable).
 * Returns `events` untouched when it already ascends — the normal streaming
 * case — so the common path costs a scan rather than a copy and a sort.
 *
 * Both full builders and the incremental one must agree here, or the same
 * transcript renders in one order while a turn streams and another once it
 * settles.
 */
export function orderEventsByTimestamp<T>(
  events: T[],
  timestampOf: (event: T) => number,
): T[] {
  for (let i = 1; i < events.length; i++) {
    if (timestampOf(events[i]) < timestampOf(events[i - 1])) {
      return events.toSorted(
        (left, right) => timestampOf(left) - timestampOf(right),
      );
    }
  }
  return events;
}

export function buildConversationItems(
  events: AcpMessage[],
  isPromptPending: boolean | null,
  options?: BuildConversationOptions,
): BuildResult {
  const b = createItemBuilder();

  const ordered = orderEventsByTimestamp(events, (event) => event.ts);
  for (const event of ordered) {
    processEvent(b, event, options);
  }

  finalizeBuilder(b, isPromptPending);

  const lastTurnInfo = readLastTurnInfo(b);

  return {
    items: b.items,
    lastTurnInfo,
    isCompacting: b.isCompacting,
    isClearing: b.isClearing,
    completedToolCallCount: b.completedToolCallCount,
    lastActivityAt: b.lastActivityAt,
    isBackgroundTurnActive: b.isBackgroundTurnActive,
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
  noteActivity(b, event.ts);

  if (isJsonRpcNotification(msg)) {
    handleNotification(b, msg, event.ts, options);
    return;
  }

  if (isJsonRpcRequest(msg) && msg.method === "session/prompt") {
    if (isSteerPromptParams(msg.params)) {
      handleSteerPromptRequest(b, msg, event.ts);
    } else {
      handlePromptRequest(b, msg, event.ts);
    }
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
  const ordered = orderEventsByTimestamp(events, (event) => event.timestamp);

  for (const event of ordered) {
    processAgentConversationEvent(b, event);
  }

  finalizeBuilder(b, isPromptPending);

  return {
    items: b.items,
    lastTurnInfo: readLastTurnInfo(b),
    isCompacting: b.isCompacting,
    isClearing: b.isClearing,
    completedToolCallCount: b.completedToolCallCount,
    lastActivityAt: b.lastActivityAt,
    isBackgroundTurnActive: b.isBackgroundTurnActive,
  };
}

export function processAgentConversationEvent(
  b: ItemBuilder,
  event: AgentConversationEvent,
): void {
  noteActivity(b, event.timestamp);

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

  if (event.type === "progress") {
    handleProgress(b, event, event.timestamp, {
      waitForRunStarted: false,
      appendOnSetupRestart: true,
    });
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

  if (event.type === "queue_update") {
    return;
  }

  if (event.type === "turn_completed" && b.currentTurn) {
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

function handleSteerPromptRequest(
  b: ItemBuilder,
  msg: { id: number | string; params?: unknown },
  ts: number,
) {
  const userPrompt = extractUserPrompt(msg.params);

  if (
    userPrompt.content.trim().length === 0 &&
    userPrompt.attachments.length === 0
  ) {
    return;
  }

  b.items.push({
    type: "user_message",
    id: `steer-${ts}-${msg.id}`,
    content: userPrompt.content,
    timestamp: ts,
    attachments: userPrompt.attachments,
  });
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
    nextItemId: 0,
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

  if (isNotification(msg.method, POSTHOG_NOTIFICATIONS.PERMISSION_REQUEST)) {
    // Permission frames persist in the run log, so recovering the plan here
    // also covers reloads and historical replays — unlike the pending
    // permission in the session store, which is dropped once answered.
    const toolCall = (
      msg.params as
        | { toolCall?: { toolCallId?: unknown; rawInput?: unknown } }
        | undefined
    )?.toolCall;
    const plan = recoveredPlanOf(toolCall?.rawInput);
    if (
      typeof toolCall?.toolCallId === "string" &&
      toolCall.toolCallId &&
      plan
    ) {
      b.recoveredPlans.set(toolCall.toolCallId, plan);
      applyRecoveredPlan(b, toolCall.toolCallId);
    }
    return;
  }

  if (
    isNotification(msg.method, POSTHOG_NOTIFICATIONS.BACKGROUND_TURN_STARTED)
  ) {
    b.isBackgroundTurnActive = true;
    return;
  }

  if (
    isNotification(msg.method, POSTHOG_NOTIFICATIONS.TURN_COMPLETE) ||
    isNotification(msg.method, POSTHOG_NOTIFICATIONS.BACKGROUND_TURN_COMPLETE)
  ) {
    b.isBackgroundTurnActive = false;
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
    if (!options?.showDebugLogs) return;
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

  if (isNotification(msg.method, POSTHOG_NOTIFICATIONS.CONVERSATION_CLEARED)) {
    ensureImplicitTurn(b, ts);
    markRuntimeStatusComplete(b, "clearing");
    pushItem(b, { sessionUpdate: "conversation_cleared" });
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
  } else if (status.status === "clearing") {
    if (status.isComplete) {
      markRuntimeStatusComplete(b, "clearing");
      return;
    }
    // The /clear prompt RPC keeps isPromptPending true for the whole swap,
    // so without this flag the generic "Generating…" footer would render
    // alongside the dedicated "Clearing…" row (compaction has the same
    // gate via isCompacting).
    b.isClearing = true;
  } else if (status.status === "clearing_failed") {
    // A timed-out clear emits no `conversation_cleared` marker, so clear
    // the spinner and render the outcome as its own status row.
    markRuntimeStatusComplete(b, "clearing");
    pushItem(b, {
      sessionUpdate: "status",
      status: "clearing_failed",
      error: status.error,
    });
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

function syncProgressCard(
  card: ProgressCardState,
  b: ItemBuilder,
  waitForRunStarted = true,
) {
  const gateAgentStep =
    waitForRunStarted &&
    card.runId !== "" &&
    !b.runStartedRunIds.has(card.runId);
  const ordered: Step[] = Array.from(card.steps.values()).map((step) =>
    step.key === "agent" && step.status === "completed" && gateAgentStep
      ? { ...step, status: "in_progress" as StepStatus }
      : step,
  );
  const renderItem = {
    sessionUpdate: "progress_group" as const,
    steps: ordered,
    isActive: ordered.some((step) => step.status === "in_progress"),
  };
  card.renderItem = renderItem;

  const item = b.items[card.itemIndex];
  if (
    item?.type === "session_update" &&
    item.update.sessionUpdate === "progress_group"
  ) {
    b.items[card.itemIndex] = { ...item, update: renderItem };
  }
}

function handleProgress(
  b: ItemBuilder,
  rawParams: unknown,
  ts: number,
  options?: {
    waitForRunStarted?: boolean;
    appendOnSetupRestart?: boolean;
  },
) {
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
  const existingCard = b.progressCards.get(params.group);
  const previousAgentStatus = existingCard?.steps.get("agent")?.status;
  const startsNewSetup =
    options?.appendOnSetupRestart === true &&
    params.step === "sandbox" &&
    status === "in_progress" &&
    previousAgentStatus !== undefined &&
    previousAgentStatus !== "in_progress";
  if (startsNewSetup) {
    b.progressCards.delete(params.group);
  }

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
  syncProgressCard(card, b, options?.waitForRunStarted);
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
  if (status === "clearing") {
    b.isClearing = false;
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
  // Entries with a missing or unparseable timestamp all share one `ts`, so the
  // item index is what keeps two implicit turns from emitting the same item ids.
  const turnId = `turn-${ts}-implicit-${b.currentTurnStartIndex}`;
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
    nextItemId: 0,
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
    id: `${turn.id}-child-${turn.nextItemId++}`,
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
      id: `${turn.id}-child-${turn.nextItemId++}`,
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
      applyRecoveredPlan(b, update.toolCallId);
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
        applyRecoveredPlan(b, update.toolCallId);
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
