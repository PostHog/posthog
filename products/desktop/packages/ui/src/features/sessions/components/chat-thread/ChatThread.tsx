import {
  CaretDown,
  Check,
  Copy,
  FileText,
  Robot,
  Scroll,
  ThumbsDown,
  ThumbsUp,
} from "@phosphor-icons/react";
import { WorkerPoolContextProvider } from "@pierre/diffs/react";
import { channelDisplayLabel } from "@posthog/core/canvas/channelName";
import { useService } from "@posthog/di/react";
import {
  Button,
  ChatBubble,
  ChatBubbleContent,
  ChatMarker,
  ChatMarkerContent,
  ChatMessage,
  ChatMessageContent,
  ChatMessageFooter,
  ChatMessageHeader,
  ChatMessageScroller,
  ChatMessageScrollerButton,
  ChatMessageScrollerContent,
  ChatMessageScrollerItem,
  ChatMessageScrollerProvider,
  ChatMessageScrollerViewport,
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuTrigger,
  cn,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
  useChatMessageScroller,
  useChatMessageScrollerScrollable,
  useChatMessageScrollerVisibility,
} from "@posthog/quill";
import type {
  AcpMessage,
  AgentConversationEvent,
  AgentTurnFeedbackSentiment,
} from "@posthog/shared";
import { ANALYTICS_EVENTS, PROJECT_BLUEBIRD_FLAG } from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import { SHORTCUTS } from "@posthog/ui/features/command/keyboard-shortcuts";
import { useSmoothedText } from "@posthog/ui/features/editor/components/useSmoothedText";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { usePanelLayoutStore } from "@posthog/ui/features/panels/panelLayoutStore";
import type {
  BuildResult,
  ConversationItem,
} from "@posthog/ui/features/sessions/components/buildConversationItems";
import {
  ChatMarkdown,
  ChatStreamingMarkdown,
} from "@posthog/ui/features/sessions/components/chat-thread/ChatMarkdown";
import { ChatThreadFooter } from "@posthog/ui/features/sessions/components/chat-thread/ChatThreadFooter";
import { ChatThreadChromeProvider } from "@posthog/ui/features/sessions/components/chat-thread/chatThreadChrome";
import type { PromptRecallHandler } from "@posthog/ui/features/sessions/components/chat-thread/composerPromptRecall";
import { MessageJumpPicker } from "@posthog/ui/features/sessions/components/chat-thread/MessageJumpPicker";
import { MessageMinimap } from "@posthog/ui/features/sessions/components/chat-thread/MessageMinimap";
import { ToolGroup } from "@posthog/ui/features/sessions/components/chat-thread/ToolGroup";
import { THREAD_HOTKEY_OPTIONS } from "@posthog/ui/features/sessions/components/chat-thread/threadHotkeys";
import {
  type AgentTurn,
  CHAT_THREAD_VIRTUALIZATION_THRESHOLD,
  completedTurnTimestamp,
  countFlatRows,
  type FlatThreadRow,
  FOLLOWING_END,
  flattenTurnRows,
  keyTurnRows,
  nextThreadFollowState,
  SCROLL_PREVIOUS_ITEM_PEEK,
  SCROLL_UP_KEYS,
  sampleThreadScroll,
  type ThreadFollowState,
  type ThreadItem,
  type ThreadScrollResume,
  type TurnRow,
} from "@posthog/ui/features/sessions/components/chat-thread/threadVirtualization";
import { buildTurnCopyText } from "@posthog/ui/features/sessions/components/chat-thread/turnCopyText";
import { usePromptRecallSource } from "@posthog/ui/features/sessions/components/chat-thread/usePromptRecallSource";
import { VirtualThreadScrollBody } from "@posthog/ui/features/sessions/components/chat-thread/VirtualThreadScrollBody";
import {
  copyFromContextMenu,
  getSelectionWithin,
} from "@posthog/ui/features/sessions/components/copyContextTarget";
import { GitActionMessage } from "@posthog/ui/features/sessions/components/GitActionMessage";
import { GitActionResult } from "@posthog/ui/features/sessions/components/GitActionResult";
import { isUserInitiatedConversationItem } from "@posthog/ui/features/sessions/components/isUserInitiatedConversationItem";
import { mergeConversationItems } from "@posthog/ui/features/sessions/components/mergeConversationItems";
import { isPlanItem } from "@posthog/ui/features/sessions/components/new-thread/buildThreadGroups";
import { extractCanvasInstructions } from "@posthog/ui/features/sessions/components/session-update/canvasInstructions";
import { extractChannelContext } from "@posthog/ui/features/sessions/components/session-update/channelContext";
import { extractCustomInstructions } from "@posthog/ui/features/sessions/components/session-update/customInstructions";
import {
  extractOnboardingBrief,
  ONBOARDING_BRIEF_LABEL,
} from "@posthog/ui/features/sessions/components/session-update/onboardingBrief";
import {
  hasFileMentions,
  MentionChip,
  parseFileMentions,
} from "@posthog/ui/features/sessions/components/session-update/parseFileMentions";
import { extractPeerAgentMessage } from "@posthog/ui/features/sessions/components/session-update/peerAgentMessage";
import { collapsePiSkillInvocation } from "@posthog/ui/features/sessions/components/session-update/piSkillInvocation";
import { SessionUpdateView } from "@posthog/ui/features/sessions/components/session-update/SessionUpdateView";
import { UserShellExecuteView } from "@posthog/ui/features/sessions/components/session-update/UserShellExecuteView";
import { UserMessageAttachments } from "@posthog/ui/features/sessions/components/UserMessageAttachments";
import {
  CHAT_CONTENT_MAX_WIDTH,
  CHAT_CONTENT_PADDING_INLINE,
} from "@posthog/ui/features/sessions/constants";
import { DIFFS_HIGHLIGHTER_OPTIONS } from "@posthog/ui/features/sessions/diffHighlighterOptions";
import { useAgentConversationItems } from "@posthog/ui/features/sessions/hooks/useAgentConversationItems";
import { useConversationItems } from "@posthog/ui/features/sessions/hooks/useConversationItems";
import {
  useOptimisticItemsForTask,
  useSessionIsCloud,
} from "@posthog/ui/features/sessions/sessionStore";
import {
  useSessionViewActions,
  useShowRawLogs,
  useTurnFeedback,
} from "@posthog/ui/features/sessions/sessionViewStore";
import { useThreadScrollRequest } from "@posthog/ui/features/sessions/threadNavigationStore";
import type { UserMessageAttachment } from "@posthog/ui/features/sessions/userMessageTypes";
import {
  SessionTaskIdProvider,
  useSessionTaskId,
} from "@posthog/ui/features/sessions/useSessionTaskId";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { TIP_KEYS } from "@posthog/ui/features/settings/tipKeys";
import { SkillButtonActionMessage } from "@posthog/ui/features/skill-buttons/components/SkillButtonActionMessage";
import { toast } from "@posthog/ui/primitives/toast";
import { useCopy } from "@posthog/ui/primitives/useCopy";
import { track } from "@posthog/ui/shell/analytics";
import {
  DIFF_WORKER_FACTORY,
  type DiffWorkerFactory,
} from "@posthog/ui/shell/diffWorkerHost";
import {
  memo,
  type ReactElement,
  type ReactNode,
  type RefObject,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useHotkeys } from "react-hotkeys-hook";

type SessionUpdateItem = Extract<ConversationItem, { type: "session_update" }>;

function isToolCallItem(item: ConversationItem): item is SessionUpdateItem {
  return (
    item.type === "session_update" && item.update.sessionUpdate === "tool_call"
  );
}

function isSessionUpdateItem(
  item: ConversationItem,
): item is SessionUpdateItem {
  return item.type === "session_update";
}

/**
 * Session-updates that `SessionUpdateView` always renders as `null`. They produce no row, so they
 * must not break a contiguous tool run.
 */
const INVISIBLE_UPDATES = new Set([
  "user_message_chunk",
  "tool_call_update",
  "plan",
  "available_commands_update",
  "config_option_update",
]);

/**
 * True when an item renders nothing, so it should be transparent to tool grouping. Besides the
 * always-null updates, this covers text chunks the stream emits with empty/whitespace or non-text
 * content (a stray empty `agent_message_chunk` between two tool calls is hidden via `empty:hidden`
 * but would otherwise split the run into two ungrouped markers).
 */
function isInvisibleItem(item: ConversationItem): boolean {
  if (item.type !== "session_update") return false;
  const update = item.update;
  if (INVISIBLE_UPDATES.has(update.sessionUpdate)) return true;
  if (
    update.sessionUpdate === "agent_message_chunk" ||
    update.sessionUpdate === "agent_thought_chunk"
  ) {
    return update.content.type !== "text" || update.content.text.trim() === "";
  }
  return false;
}

/**
 * A thought joins a tool run instead of breaking it, because between two calls it narrates the
 * stretch of work the run already stands for. The group's body still lists it in order. Prose to
 * the user (`agent_message_chunk`) does break a run, since that is addressed to the reader rather
 * than describing the work.
 */
function isThoughtItem(item: ConversationItem): boolean {
  return (
    item.type === "session_update" &&
    item.update.sessionUpdate === "agent_thought_chunk"
  );
}

/**
 * Collapse each contiguous run of ≥2 tool-call updates into a single `ToolGroupItem`. A run is
 * broken by any *visible* non-tool, non-thought item (prose, status) so groups follow reading
 * order; invisible updates (see {@link INVISIBLE_UPDATES}) are transparent and don't split a run.
 * A lone tool call passes through untouched as a single marker, and so do the thoughts around it:
 * thoughts ride along a run, they never make one.
 */
/**
 * Item arrays for settled runs, keyed on the run's (stable) first item.
 *
 * Grouping re-runs over the whole thread on every streamed chunk, so a completed run produces a
 * fresh array with identical contents each time. New identity defeats `ToolGroup`'s `memo`, which
 * makes every settled group above the live one re-render per chunk. Handing back the previous
 * array lets them skip the render.
 *
 * Only safe once the run's turn is complete, because a live tool's status is mutated in place on
 * its resolved `ToolCall`: reusing an array mid-turn would leave a spinner on a tool that has
 * since finished. `len` covers a run that gains items before it settles.
 */
const settledRunItems = new WeakMap<
  ConversationItem,
  { len: number; items: SessionUpdateItem[] }
>();

function stableRunItems(run: SessionUpdateItem[]): SessionUpdateItem[] {
  if (!run.at(-1)?.turnContext.turnComplete) return run;
  const key = run[0];
  const cached = settledRunItems.get(key);
  if (cached && cached.len === run.length) return cached.items;
  settledRunItems.set(key, { len: run.length, items: run });
  return run;
}

export function groupToolRuns(items: ConversationItem[]): ThreadItem[] {
  const out: ThreadItem[] = [];
  // The buffer holds the active run in order: tools, the thoughts between them, and any invisible
  // items interleaved with either.
  let buffer: ConversationItem[] = [];
  let toolCount = 0;

  const flush = () => {
    if (toolCount >= 2) {
      out.push({
        type: "tool_group",
        // Keyed on the first tool call so the id survives thoughts appending around it.
        id: buffer.filter(isToolCallItem)[0].id,
        items: stableRunItems(buffer.filter(isSessionUpdateItem)),
      });
    } else {
      out.push(...buffer);
    }
    buffer = [];
    toolCount = 0;
  };

  for (const item of items) {
    if (isToolCallItem(item)) {
      // A plan presented for approval renders as the full PlanApprovalView
      // card — folded into a "N tool calls" chip, the plan the user is being
      // asked to approve is invisible. Same exemption as buildThreadGroups.
      if (isPlanItem(item)) {
        flush();
        out.push(item);
        continue;
      }
      buffer.push(item);
      toolCount++;
    } else if (isInvisibleItem(item) || isThoughtItem(item)) {
      // Don't break the run; carry it along in order.
      buffer.push(item);
    } else {
      flush();
      out.push(item);
    }
  }
  flush();
  return out;
}

/**
 * Collapse each contiguous run of non-user rows into one {@link AgentTurn}, broken only by a
 * user-initiated row (which stays standalone so it remains the scroll anchor for the sticky header
 * and auto-follow). The turn block renders as a single muted card, tightening the spacing between
 * the agent's successive replies and tool calls. Each turn records the user-initiated row that
 * opened it, so "Copy turn" can lead with the prompt the turn answered.
 */
function groupIntoTurns(rows: ThreadItem[]): TurnRow[] {
  const out: TurnRow[] = [];
  let buffer: ThreadItem[] = [];
  let prompt: ThreadItem | undefined;
  const flush = () => {
    if (buffer.length > 0) {
      out.push({ type: "agent_turn", id: buffer[0].id, items: buffer, prompt });
      buffer = [];
    }
  };
  for (const row of rows) {
    // git_action and skill_button_action stand in for the user's message when the prompt was a
    // git operation or a skill button click (see handlePromptRequest) — they open a turn just
    // like a user message, so they break the agent card too rather than render inside it as if
    // they were agent output. Same boundary set as the legacy view's buildThreadGroups.
    if (isUserInitiatedConversationItem(row)) {
      flush();
      out.push(row);
      prompt = row;
    } else {
      buffer.push(row);
    }
  }
  flush();
  return out;
}

function formatTimestamp(ts: number): string {
  return new Date(ts).toLocaleString([], {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  });
}

/**
 * Hover-revealed footer under a completed agent turn: the turn's timestamp, a button copying the
 * agent response, and thumbs to rate it. Rendered right-aligned under agent-side content — the
 * end-aligned user bubble keeps its own footer — inside a `group` container, so it fades in only
 * while that turn is hovered. Once per turn rather than per row, which was too noisy.
 *
 * A rated turn keeps its footer on screen, so the reader can see which thumb they picked without
 * hovering to find out.
 */
function TurnFooter({
  turnId,
  timestamp,
  copyText,
}: {
  turnId: string;
  timestamp?: number;
  copyText?: string;
}) {
  const sentiment = useTurnFeedback(turnId);
  if (timestamp == null) return null;
  return (
    <ChatMessageFooter
      className={cn(
        "mt-2 items-center justify-end gap-1 pl-0 transition-opacity",
        sentiment ? "opacity-100" : "opacity-0 group-hover:opacity-100",
      )}
    >
      <span className="text-muted-foreground">
        {formatTimestamp(timestamp)}
      </span>
      {copyText && <CopyButton value={copyText} label="Copy turn" />}
      <TurnFeedback turnId={turnId} sentiment={sentiment} />
    </ChatMessageFooter>
  );
}

/**
 * Thumbs on a completed agent turn, next to the copy button rather than behind the right-click
 * menu — rating a reply is a thing you do to the message, not to the text you happen to have
 * highlighted.
 *
 * The rating submits on the first click and is analytics-only: it never changes the session, so
 * there is nothing to confirm. Re-clicking the lit thumb is a no-op rather than a second identical
 * event; switching thumbs records the new sentiment.
 */
function TurnFeedback({
  turnId,
  sentiment,
}: {
  turnId: string;
  sentiment: AgentTurnFeedbackSentiment | null;
}) {
  const taskId = useSessionTaskId();
  const { setTurnFeedback } = useSessionViewActions();

  const rate = (next: AgentTurnFeedbackSentiment) => {
    if (sentiment === next) return;
    setTurnFeedback(turnId, next);
    track(ANALYTICS_EVENTS.AGENT_TURN_FEEDBACK, {
      task_id: taskId,
      turn_id: turnId,
      sentiment: next,
    });
  };

  return (
    <>
      <FooterIconButton label="Good response" onClick={() => rate("positive")}>
        <ThumbsUp
          size={12}
          weight={sentiment === "positive" ? "fill" : undefined}
        />
      </FooterIconButton>
      <FooterIconButton label="Bad response" onClick={() => rate("negative")}>
        <ThumbsDown
          size={12}
          weight={sentiment === "negative" ? "fill" : undefined}
        />
      </FooterIconButton>
    </>
  );
}

/**
 * Shared icon affordance for the message and turn footers. Stays muted whether idle or active — the
 * icon carries the state, so the row never lights up in a colour the thread doesn't use elsewhere.
 */
function FooterIconButton({
  label,
  tooltip,
  open,
  onOpenChange,
  onClick,
  children,
}: {
  label: string;
  /** Defaults to `label`; pass it separately when the tooltip has to say more than the button is. */
  tooltip?: string;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <Tooltip open={open} onOpenChange={onOpenChange}>
      <TooltipTrigger
        render={
          <Button
            variant="default"
            size="icon-xs"
            aria-label={label}
            onClick={onClick}
            className="text-muted-foreground hover:text-foreground"
          >
            {children}
          </Button>
        }
      />
      <TooltipContent>{tooltip ?? label}</TooltipContent>
    </Tooltip>
  );
}

function CopyButton({ value, label }: { value: string; label: string }) {
  const { copied, copy } = useCopy();
  const [hovered, setHovered] = useState(false);
  return (
    // Held open for the life of the `copied` window so the confirmation lands even when the click
    // moves the pointer off the button; hover drives it the rest of the time.
    <FooterIconButton
      label={label}
      tooltip={copied ? "Copied!" : label}
      open={copied || hovered}
      onOpenChange={setHovered}
      onClick={() => copy(value)}
    >
      {copied ? <Check size={12} /> : <Copy size={12} />}
    </FooterIconButton>
  );
}

/**
 * End-aligned user bubble. The text is clamped to five lines (`max-height: 5lh` + `overflow-hidden`,
 * which — unlike `-webkit-line-clamp` — reliably clamps markdown's block `<p>` children); a "Show
 * more" toggle appears only when the content actually exceeds the clamp, so short messages never
 * grow a toggle. Overflow can't be known
 * from character count (it depends on wrapping width), so we measure `scrollHeight` against the
 * clamped `clientHeight` — which holds even while clamped — and re-measure on resize.
 *
 * A channel's CONTEXT.md and the canvas generation instructions, if injected into this prompt, are
 * collapsed into a clickable `ChatMessageHeader` chip above the bubble (opening the snapshot as a
 * split tab) rather than rendered inline — a project-bluebird feature. The blocks are always stripped
 * (along with the always-on personalization block) so the raw XML never leaks for flag-off viewers.
 * The send timestamp sits in a `ChatMessageFooter` revealed on hover.
 */
function UserBubble({
  content,
  timestamp,
  attachments = [],
  keyboardFocused = false,
}: {
  content: string;
  timestamp?: number;
  attachments?: UserMessageAttachment[];
  keyboardFocused?: boolean;
}) {
  const bluebirdEnabled = useFeatureFlag(
    PROJECT_BLUEBIRD_FLAG,
    import.meta.env.DEV,
  );
  // A message relayed from another agent run renders as an incoming agent
  // message (start-aligned, outlined, provenance chip) instead of masquerading
  // as something this run's user typed. The envelope boilerplate never renders;
  // only the sender-authored body flows into the normal pipeline below.
  const peerAgentMessage = useMemo(
    () => extractPeerAgentMessage(content),
    [content],
  );
  const baseContent = peerAgentMessage ? peerAgentMessage.body : content;
  const channelContext = useMemo(
    () => extractChannelContext(baseContent),
    [baseContent],
  );
  const afterChannelContext = channelContext
    ? channelContext.stripped
    : baseContent;
  const canvasInstructions = useMemo(
    () => extractCanvasInstructions(afterChannelContext),
    [afterChannelContext],
  );
  const afterCanvasInstructions = canvasInstructions
    ? canvasInstructions.stripped
    : afterChannelContext;
  const customInstructions = useMemo(
    () => extractCustomInstructions(afterCanvasInstructions),
    [afterCanvasInstructions],
  );
  const afterCustomInstructions = customInstructions
    ? customInstructions.stripped
    : afterCanvasInstructions;
  const onboardingBrief = useMemo(
    () => extractOnboardingBrief(afterCustomInstructions),
    [afterCustomInstructions],
  );
  const displayContent = collapsePiSkillInvocation(
    onboardingBrief ? onboardingBrief.stripped : afterCustomInstructions,
  );
  const showChannelContextTag = !!channelContext && bluebirdEnabled;
  const showCanvasInstructionsTag = !!canvasInstructions && bluebirdEnabled;
  // Provenance is never flag-gated: a peer message must not read as the user's.
  const showHeaderChips =
    !!peerAgentMessage ||
    showChannelContextTag ||
    showCanvasInstructionsTag ||
    !!onboardingBrief;
  const taskId = useSessionTaskId();
  const openChannelContextInSplit = usePanelLayoutStore(
    (s) => s.openChannelContextInSplit,
  );
  const openCanvasInstructionsInSplit = usePanelLayoutStore(
    (s) => s.openCanvasInstructionsInSplit,
  );

  const containsFileMentions = hasFileMentions(displayContent);

  const [isExpanded, setIsExpanded] = useState(false);
  const [isOverflowing, setIsOverflowing] = useState(false);
  const textRef = useRef<HTMLDivElement>(null);

  // Only meaningful while collapsed: expanding removes the clamp so scrollHeight === clientHeight.
  // We keep the prior result when expanded so the "Show less" trigger stays put.
  // biome-ignore lint/correctness/useExhaustiveDependencies: re-measure when the message text changes.
  useLayoutEffect(() => {
    if (isExpanded) return;
    const el = textRef.current;
    if (!el) return;
    const measure = () =>
      setIsOverflowing(el.scrollHeight - el.clientHeight > 1);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, [displayContent, isExpanded]);

  return (
    <MessageContextMenu value={displayContent}>
      <ChatMessage align={peerAgentMessage ? "start" : "end"} className="group">
        <ChatMessageContent className="gap-1">
          {showHeaderChips && (
            <ChatMessageHeader className="flex-wrap gap-1">
              {peerAgentMessage && (
                <MentionChip
                  icon={<Robot size={12} />}
                  label={`From agent: ${peerAgentMessage.senderTaskTitle}`}
                />
              )}
              {onboardingBrief && (
                <MentionChip
                  icon={<FileText size={12} />}
                  label={ONBOARDING_BRIEF_LABEL}
                />
              )}
              {showChannelContextTag && channelContext && (
                <MentionChip
                  icon={<FileText size={12} />}
                  label={`${
                    channelContext.mention.name
                      ? `${channelDisplayLabel(channelContext.mention.name)} `
                      : ""
                  }CONTEXT.md`}
                  onClick={
                    taskId
                      ? () =>
                          openChannelContextInSplit(taskId, {
                            channelName: channelContext.mention.name,
                            body: channelContext.mention.body,
                          })
                      : undefined
                  }
                />
              )}
              {showCanvasInstructionsTag && canvasInstructions && (
                <MentionChip
                  icon={<Scroll size={12} />}
                  label="Canvas instructions"
                  onClick={
                    taskId
                      ? () =>
                          openCanvasInstructionsInSplit(taskId, {
                            body: canvasInstructions.body,
                          })
                      : undefined
                  }
                />
              )}
            </ChatMessageHeader>
          )}
          {/* The brief is the whole message, so stripping it leaves nothing to put in a bubble. */}
          {(!!displayContent || attachments.length > 0) && (
            <ChatBubble
              align={peerAgentMessage ? "start" : "end"}
              variant={peerAgentMessage ? "outline" : "default"}
              className={cn(
                "rounded-lg ring-(--gray-11) ring-0 ring-inset transition-shadow",
                keyboardFocused && "ring-[3px]",
              )}
            >
              <ChatBubbleContent>
                <div
                  ref={textRef}
                  className={cn(
                    "[&_p]:my-0",
                    !isExpanded && "max-h-[5lh] overflow-hidden",
                    // Fade the clamped text out at the bottom so it reads as "continues below". Only
                    // when actually overflowing — a short collapsed message shouldn't fade. The mask is
                    // paint-only, so it doesn't affect the overflow measurement above.
                    !isExpanded &&
                      isOverflowing &&
                      "[mask-image:linear-gradient(to_bottom,black_45%,transparent)]",
                  )}
                >
                  {containsFileMentions ? (
                    parseFileMentions(displayContent)
                  ) : (
                    <ChatMarkdown content={displayContent} />
                  )}
                </div>
                {attachments.length > 0 && !containsFileMentions && (
                  <div className="mt-1.5">
                    <UserMessageAttachments attachments={attachments} />
                  </div>
                )}
                {isOverflowing && (
                  <button
                    type="button"
                    onClick={() => setIsExpanded((v) => !v)}
                    className="mt-1 flex items-center gap-0.5 text-muted-foreground text-sm hover:text-foreground"
                  >
                    Show {isExpanded ? "less" : "more"}
                    <CaretDown
                      className={cn("size-3", isExpanded && "rotate-180")}
                    />
                  </button>
                )}
              </ChatBubbleContent>
            </ChatBubble>
          )}
          {timestamp != null && (
            <ChatMessageFooter className="items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100">
              {formatTimestamp(timestamp)}
              <CopyButton value={displayContent} label="Copy message" />
            </ChatMessageFooter>
          )}
        </ChatMessageContent>
      </ChatMessage>
    </MessageContextMenu>
  );
}

/**
 * Right-click a message to copy it. Replaces the per-message copy button that used to float in the
 * message's right rail — the turn footer covers the common case, so a single message's copy lives
 * here instead of costing every row a hover affordance.
 *
 * This menu sits inside `SessionView`'s own context menu and wins the event over it, so it also
 * carries that menu's raw-logs toggle; without it, right-clicking a message would be the one spot
 * in the session where the toggle went missing.
 *
 * Highlighted text wins over the message: right-clicking a selection copies just that, as it does
 * outside the app. The whole message is the fallback for a right-click with nothing selected, and
 * stays reachable without the menu through the footer's copy button.
 *
 * The write goes through {@link copyFromContextMenu}: a synchronous write from a closing menu
 * rejects while focus is still being restored, and both outcomes surface as toasts — a silent
 * failure would leave the clipboard's previous contents where the user believes the message is.
 */
function MessageContextMenu({
  value,
  children,
}: {
  value: string;
  children: ReactElement;
}) {
  const showRawLogs = useShowRawLogs();
  const { setShowRawLogs } = useSessionViewActions();
  const [selection, setSelection] = useState<string | null>(null);
  return (
    <ContextMenu>
      <ContextMenuTrigger
        className="select-text"
        onContextMenu={(event) =>
          setSelection(getSelectionWithin(event.currentTarget))
        }
        render={children}
      />
      <ContextMenuContent>
        <ContextMenuItem
          onClick={() =>
            copyFromContextMenu(selection ?? value, {
              onSuccess: () => toast.success("Copied"),
              onError: () => toast.error("Couldn't copy"),
            })
          }
        >
          <Copy size={14} />
          {selection ? "Copy selection" : "Copy message"}
        </ContextMenuItem>
        <ContextMenuSeparator />
        <ContextMenuItem onClick={() => setShowRawLogs(!showRawLogs)}>
          <Scroll size={14} />
          {showRawLogs ? "Back to conversation" : "Show raw logs"}
        </ContextMenuItem>
      </ContextMenuContent>
    </ContextMenu>
  );
}

/**
 * Start-aligned assistant prose bubble. Streamed tokens arrive in bursts; `useSmoothedText` reveals
 * them at a steady character rate so the text reads as even typing (text present on mount shows
 * immediately, so completed messages render in full with no replay).
 *
 * While streaming, the smoothed reveal re-renders every animation frame, so the markdown goes
 * through `ChatStreamingMarkdown` (block-split: each frame re-parses only the tail block). Once the
 * turn completes it swaps to a single full `ChatMarkdown` parse.
 */
const AgentProse = memo(function AgentProse({
  text,
  isStreaming = false,
}: {
  text: string;
  isStreaming?: boolean;
}) {
  const smoothed = useSmoothedText(text);

  return (
    <MessageContextMenu value={text}>
      <ChatMessage align="start" className="group/msg">
        <ChatMessageContent className="gap-1">
          <ChatBubble variant="ghost">
            <ChatBubbleContent>
              {isStreaming ? (
                <ChatStreamingMarkdown content={smoothed} renderObjectTags />
              ) : (
                <ChatMarkdown content={text} renderObjectTags />
              )}
            </ChatBubbleContent>
          </ChatBubble>
        </ChatMessageContent>
      </ChatMessage>
    </MessageContextMenu>
  );
});

/** Renders a single thread item's body (no scroller wrapper), reused for standalone rows and for
 * each item inside an agent-turn card. `isTrailing` marks the turn's last item — a trailing tool
 * group of a streaming turn may still grow, so its label stays "Using …" between tool calls. */
function ThreadItemBody({
  item,
  renderItem,
  isTrailing = false,
  keyboardFocused = false,
}: {
  item: ThreadItem;
  renderItem: (item: ConversationItem) => ReactNode;
  isTrailing?: boolean;
  keyboardFocused?: boolean;
}) {
  if (item.type === "tool_group") {
    const context = item.items[0]?.turnContext;
    const turnStreaming =
      !!context && !context.turnComplete && !context.turnCancelled;
    return (
      <ToolGroup
        items={item.items}
        mayStillGrow={isTrailing && turnStreaming}
      />
    );
  }
  if (item.type === "user_message") {
    return (
      <UserBubble
        content={item.content}
        timestamp={item.timestamp}
        attachments={item.attachments}
        keyboardFocused={keyboardFocused}
      />
    );
  }
  return <>{renderItem(item)}</>;
}

/**
 * One transcript row. Memoized and scroll-state-free, so rows never re-render while scrolling — the
 * non-virtualized thread stays cheap. The pinned header is the separate overlay, not the rows.
 *
 * An {@link AgentTurn} renders as a single muted card wrapping its items with tight spacing; a user
 * message stays a standalone anchored row.
 */
const ThreadRow = memo(function ThreadRow({
  item,
  renderItem,
  keyboardFocused,
}: {
  item: TurnRow;
  renderItem: (item: ConversationItem) => ReactNode;
  keyboardFocused?: boolean;
}) {
  if (item.type === "agent_turn") {
    return (
      <ChatMessageScrollerItem
        messageId={item.id}
        scrollAnchor={false}
        className="group mx-auto w-full empty:hidden"
        style={{ maxWidth: CHAT_CONTENT_MAX_WIDTH }}
      >
        <div className="flex flex-col gap-4 empty:hidden">
          {item.items.map((sub, i) => (
            // The scroller item's own content-visibility works at whole-turn granularity — a
            // large turn (diffs, charts, dozens of tools) would render wholesale as soon as the
            // card nears the viewport. Nesting content-visibility per sub-item keeps layout +
            // paint bounded to the viewport-sized slice while scrolling; `auto` remembers each
            // row's real size after first render so the scrollbar stays stable.
            <div
              key={sub.id}
              className="[contain-intrinsic-size:auto_2rem] [content-visibility:auto] empty:hidden"
            >
              <ThreadItemBody
                item={sub}
                renderItem={renderItem}
                isTrailing={i === item.items.length - 1}
              />
            </div>
          ))}
        </div>
        <TurnFooter
          turnId={item.id}
          timestamp={completedTurnTimestamp(item)}
          copyText={buildTurnCopyText(item.items) ?? undefined}
        />
      </ChatMessageScrollerItem>
    );
  }
  return (
    <ChatMessageScrollerItem
      messageId={item.id}
      scrollAnchor={item.type === "user_message"}
      className="mx-auto w-full py-1 empty:hidden"
      style={{ maxWidth: CHAT_CONTENT_MAX_WIDTH }}
    >
      <ThreadItemBody
        item={item}
        renderItem={renderItem}
        keyboardFocused={keyboardFocused}
      />
    </ChatMessageScrollerItem>
  );
});

/**
 * Keeps the view pinned to the bottom until the user scrolls away, re-arming on each prompt submit.
 *
 * The engine's own follow mode isn't enough on its own:
 * - It only re-engages within `scrollEdgeThreshold` of the exact bottom, so a submit from anywhere
 *   higher would leave the new prompt (and the reply) below the fold. Scrolling to the end on
 *   submit also flips the engine back into `following-bottom`.
 * - Each engine autoscroll is guarded by a 180ms grace window; a large streamed block (heavy
 *   markdown render) can jank past it, making the engine observe "content below the fold while not
 *   autoscrolling" and silently demote itself to `free-scrolling` mid-reply. While armed, any
 *   commit that leaves content below the fold re-issues `scrollToEnd` to recapture follow.
 *
 * It arms on mount so a thread the reader is only watching — a cloud task streaming into a command
 * center panel, with no prompt sent from here — still follows. Scrolling upward disarms it, which
 * is the half the engine gets wrong: the engine re-derives follow from scroll position and so
 * overrules the gesture. Scrolling back down to the end re-arms it, a submit or the
 * scroll-to-bottom button re-arms it from anywhere.
 */
function ThreadAutoFollow({
  items,
  followRef,
}: {
  items: ConversationItem[];
  /** Owned by the body so the scroll-to-bottom button can re-arm the pin too. */
  followRef: RefObject<ThreadFollowState>;
}) {
  const { scrollToEnd } = useChatMessageScroller();
  const { end } = useChatMessageScrollerScrollable();
  const lastItem = items.at(-1);
  const userMessageCount = useMemo(
    () =>
      items.reduce((n, item) => (item.type === "user_message" ? n + 1 : n), 0),
    [items],
  );
  const prevCountRef = useRef(userMessageCount);
  const probeRef = useRef<HTMLSpanElement>(null);

  useLayoutEffect(() => {
    const previous = prevCountRef.current;
    prevCountRef.current = userMessageCount;
    if (previous === 0 || userMessageCount <= previous) return;
    if (lastItem?.type !== "user_message") return;
    followRef.current = FOLLOWING_END;
    scrollToEnd({ behavior: "auto" });
  }, [userMessageCount, lastItem, scrollToEnd, followRef]);

  useEffect(() => {
    const viewport = probeRef.current
      ?.closest('[data-slot="chat-message-scroller"]')
      ?.querySelector('[data-slot="chat-message-scroller-viewport"]');
    if (!(viewport instanceof HTMLElement)) return;

    // An upward gesture too small to register as a direction change below still means the reader
    // is reading, not following.
    const leaveEnd = () => {
      if (followRef.current.leftEnd || viewport.scrollTop <= 0) return;
      followRef.current = { following: false, leftEnd: true };
    };
    const onWheel = (event: Event) => {
      if ((event as WheelEvent).deltaY < 0) leaveEnd();
    };
    const onKeyDown = (event: Event) => {
      if (SCROLL_UP_KEYS.has((event as KeyboardEvent).key)) leaveEnd();
    };
    // Direction, not position: the reader who scrolls back to the bottom while the agent keeps
    // appending never lands on the exact end, so following has to resume from the gesture.
    let lastScrollTop = viewport.scrollTop;
    const onScroll = () => {
      const sample = sampleThreadScroll(viewport, lastScrollTop);
      lastScrollTop = viewport.scrollTop;
      followRef.current = nextThreadFollowState(followRef.current, sample);
    };

    viewport.addEventListener("wheel", onWheel, { passive: true });
    viewport.addEventListener("touchmove", leaveEnd, { passive: true });
    viewport.addEventListener("keydown", onKeyDown, { passive: true });
    viewport.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      viewport.removeEventListener("wheel", onWheel);
      viewport.removeEventListener("touchmove", leaveEnd);
      viewport.removeEventListener("keydown", onKeyDown);
      viewport.removeEventListener("scroll", onScroll);
    };
  }, [followRef]);

  // biome-ignore lint/correctness/useExhaustiveDependencies: re-check on every streamed change — `end` alone doesn't re-notify while it stays true across commits.
  useEffect(() => {
    if (followRef.current.following && end) {
      scrollToEnd({ behavior: "auto" });
    }
  }, [items, end, scrollToEnd, followRef]);

  return <span ref={probeRef} className="hidden" aria-hidden="true" />;
}

/**
 * Keyboard message navigation (Alt/Option+Up/Down) and the Cmd/Ctrl+J jump picker. Rendered inside
 * `ChatMessageScrollerProvider` so it can call `scrollToMessage` from the engine — the same primitive
 * `MessageMinimap` uses to jump back to an earlier turn.
 */
function ThreadKeyboardNav({
  items,
  jumpPickerOpen,
  setJumpPickerOpen,
  keyboardFocusedMessageId,
  setKeyboardFocusedMessageId,
  promptRecallRef,
  jumpToMessage,
}: {
  items: ConversationItem[];
  jumpPickerOpen: boolean;
  setJumpPickerOpen: (value: boolean | ((prev: boolean) => boolean)) => void;
  keyboardFocusedMessageId: string | null;
  setKeyboardFocusedMessageId: (id: string | null) => void;
  promptRecallRef?: RefObject<PromptRecallHandler | null>;
  /**
   * Override for the engine's `scrollToMessage`. The virtualized body supplies one that jumps by
   * row index — the engine can only scroll to mounted rows, and a windowed thread keeps most rows
   * unmounted.
   */
  jumpToMessage?: (id: string) => void;
}) {
  const { scrollToMessage } = useChatMessageScroller();
  const jump = jumpToMessage ?? scrollToMessage;

  const userMessages = useMemo(
    () =>
      items
        .filter(
          (item): item is Extract<ConversationItem, { type: "user_message" }> =>
            item.type === "user_message",
        )
        .map((item) => ({ id: item.id, content: item.content })),
    [items],
  );
  const userMessageIds = useMemo(
    () => userMessages.map((message) => message.id),
    [userMessages],
  );

  useHotkeys(
    SHORTCUTS.MESSAGE_JUMP,
    () => setJumpPickerOpen((prev) => !prev),
    THREAD_HOTKEY_OPTIONS,
  );

  const handleNavigateMessage = useCallback(
    (direction: -1 | 1) => {
      if (userMessageIds.length === 0) return;

      const currentIndex = keyboardFocusedMessageId
        ? userMessageIds.indexOf(keyboardFocusedMessageId)
        : -1;

      const nextIndex =
        currentIndex === -1
          ? direction > 0
            ? 0
            : userMessageIds.length - 1
          : Math.max(
              0,
              Math.min(userMessageIds.length - 1, currentIndex + direction),
            );

      const nextId = userMessageIds[nextIndex];
      if (!nextId) return;

      useSettingsStore.getState().markHintLearned(TIP_KEYS.recallMessageNav);
      setKeyboardFocusedMessageId(nextId);
      jump(nextId);
    },
    [
      keyboardFocusedMessageId,
      userMessageIds,
      setKeyboardFocusedMessageId,
      jump,
    ],
  );

  useHotkeys(
    SHORTCUTS.MESSAGE_PREV,
    () => handleNavigateMessage(-1),
    THREAD_HOTKEY_OPTIONS,
  );

  useHotkeys(
    SHORTCUTS.MESSAGE_NEXT,
    () => handleNavigateMessage(1),
    THREAD_HOTKEY_OPTIONS,
  );

  usePromptRecallSource(userMessages, promptRecallRef);

  const handleJumpToMessage = useCallback(
    (id: string) => {
      setKeyboardFocusedMessageId(id);
      jump(id);
    },
    [jump, setKeyboardFocusedMessageId],
  );

  return (
    <MessageJumpPicker
      open={jumpPickerOpen}
      onOpenChange={setJumpPickerOpen}
      items={items}
      onJumpToMessage={handleJumpToMessage}
    />
  );
}

/**
 * Keeps {@link ThreadScrollResume} current while the non-virtualized body is mounted, so the
 * windowed body can pick up where this one left off if the thread crosses the threshold
 * mid-session. Both values come from engine state the scroller already tracks — at-bottom from
 * `scrollable.end` (true while content extends below the fold), and the anchored user message from
 * the same visibility state the sticky header reads — so nothing here listens to scroll. Writes go
 * to a ref: the recorder must never make the thread re-render.
 */
function ThreadScrollStateRecorder({
  stateRef,
}: {
  stateRef: RefObject<ThreadScrollResume>;
}) {
  const { end } = useChatMessageScrollerScrollable();
  const { currentAnchorId } = useChatMessageScrollerVisibility();

  useEffect(() => {
    stateRef.current = { atBottom: !end, anchorId: currentAnchorId ?? null };
  }, [end, currentAnchorId, stateRef]);

  return null;
}

/** The scroll body, under the Provider so the overlay + scroll-button hooks can read engine state. */
function ThreadScrollBody({
  items,
  rows,
  renderItem,
  footer,
  keyboardFocusedMessageId,
  onUserInteract,
  resumeStateRef,
  autoFollowRef,
}: {
  items: ConversationItem[];
  rows: TurnRow[];
  renderItem: (item: ConversationItem) => ReactNode;
  /** Status row (duration / diff stats) pinned as the last item in the thread. */
  footer?: ReactElement;
  keyboardFocusedMessageId?: string | null;
  /** Clears keyboard-focused message state on any pointer interaction with the thread. */
  onUserInteract?: () => void;
  /** Continuously updated so the virtualized body can take over mid-session (see {@link ThreadScrollResume}). */
  resumeStateRef: RefObject<ThreadScrollResume>;
  autoFollowRef: RefObject<ThreadFollowState>;
}) {
  const keyedRows = useMemo(() => keyTurnRows(rows), [rows]);

  // `group/thread` so the footer's hover-reveal (opacity-50 → 100 on group-hover) tracks the thread,
  // mirroring the legacy ConversationView container. `@container/thread` makes the thread's own
  // width the query basis for everything inside it — the panel is resizable and splittable, so the
  // viewport says nothing useful about how much room a row actually has.
  return (
    <ChatMessageScroller
      className="@container/thread group/thread"
      onPointerDownCapture={onUserInteract}
    >
      <MessageMinimap items={items} />
      <ThreadAutoFollow items={items} followRef={autoFollowRef} />
      <ThreadScrollStateRecorder stateRef={resumeStateRef} />
      <ChatMessageScrollerViewport>
        <ChatMessageScrollerContent
          className="gap-4 py-4 pb-8"
          density="default"
          style={{ paddingInline: CHAT_CONTENT_PADDING_INLINE }}
        >
          {keyedRows.map(({ item, key }) => (
            <ThreadRow
              key={key}
              item={item}
              renderItem={renderItem}
              keyboardFocused={item.id === keyboardFocusedMessageId}
            />
          ))}
          {footer && (
            <div
              className="mx-auto w-full px-2.5"
              style={{ maxWidth: CHAT_CONTENT_MAX_WIDTH }}
            >
              {footer}
            </div>
          )}
        </ChatMessageScrollerContent>
      </ChatMessageScrollerViewport>
      {/* Re-arms the pin as well as scrolling: the button is the reader saying "follow again". */}
      <ChatMessageScrollerButton
        onClick={() => {
          autoFollowRef.current = FOLLOWING_END;
        }}
      />
    </ChatMessageScroller>
  );
}

const EMPTY_FLAT_ROWS: FlatThreadRow[] = [];

/**
 * One windowed row. Memoized against the row's *contents* rather than the row wrapper object —
 * `flattenTurnRows` rebuilds wrappers on every streamed chunk, but the underlying conversation
 * items are reused by reference for completed turns, so mounted rows outside the streaming tail
 * skip re-rendering their markdown/diffs.
 *
 * `content-visibility` is forced off (the quill item class sets `auto`): the virtualizer already
 * bounds the mounted set, and overscan rows must lay out for `measureElement` to size them before
 * they scroll into view — skipped rendering would feed it the placeholder intrinsic size instead.
 */
const FlatRowView = memo(
  function FlatRowView({
    row,
    renderItem,
    keyboardFocused,
  }: {
    row: FlatThreadRow;
    renderItem: (item: ConversationItem) => ReactNode;
    keyboardFocused: boolean;
  }) {
    const { item } = row;
    return (
      <ChatMessageScrollerItem
        messageId={item.id}
        scrollAnchor={false}
        className={cn(
          // pb-4 stands in for the non-virtualized content's inter-row gap-4; an empty row
          // collapses entirely (display:none hides the padding too), matching how flex gap
          // skips hidden children there.
          "mx-auto w-full pb-4 [content-visibility:visible] empty:hidden",
          row.inTurn ? "group" : "px-2.5 pt-1",
        )}
        style={{ maxWidth: CHAT_CONTENT_MAX_WIDTH }}
      >
        <ThreadItemBody
          item={item}
          renderItem={renderItem}
          isTrailing={row.isTrailingInTurn}
          keyboardFocused={keyboardFocused}
        />
        {row.turnId != null && row.turnTimestamp != null && (
          <TurnFooter
            turnId={row.turnId}
            timestamp={row.turnTimestamp}
            copyText={row.turnCopyText}
          />
        )}
      </ChatMessageScrollerItem>
    );
  },
  (prev, next) =>
    prev.row.item === next.row.item &&
    prev.row.key === next.row.key &&
    prev.row.inTurn === next.row.inTurn &&
    prev.row.isTrailingInTurn === next.row.isTrailingInTurn &&
    prev.row.turnTimestamp === next.row.turnTimestamp &&
    prev.renderItem === next.renderItem &&
    prev.keyboardFocused === next.keyboardFocused,
);

/**
 * Thread renderer built on the ChatX (quill) primitives.
 *
 * Reuses the existing parse pipeline (`useConversationItems`) and the non-virtualized
 * `ChatMessageScroller` (`content-visibility: auto`). User + assistant turns render through
 * `ChatMessage`/`ChatBubble` (end-aligned filled / start-aligned ghost) with our own `ChatMarkdown`.
 * Tool calls render as `ChatMarker` — `ChatThreadChromeProvider` flips the shared `ToolRow` chrome
 * to the ChatX primitive, so every tool view is mapped without forking. User messages carry their
 * context chips (`ChatMessageHeader`), file/attachment mentions, and a hover timestamp
 * (`ChatMessageFooter`) — see `UserBubble`.
 */
interface SharedChatThreadProps {
  /**
   * Fold each run of tool calls into one collapsible row. Defaults to true.
   *
   * Embedded surfaces (the live-agent chat preview) pass false: they are short, they are the whole
   * point of the pane they sit in, and folding the agent's work behind a chip there hides the only
   * thing there is to look at.
   */
  groupToolCalls?: boolean;
  isPromptPending: boolean | null;
  promptStartedAt?: number | null;
  promptRecallRef?: RefObject<PromptRecallHandler | null>;
  repoPath?: string | null;
  task?: Task;
  taskId?: string;
  footerState?: Omit<BuildResult, "items">;
  hasPendingPermission?: boolean;
  /**
   * Chain index of the oldest loaded entry; 0 means the whole transcript is loaded. Above 0 the
   * thread renders windowed regardless of length, because only that body survives a prepend.
   */
  olderHistoryCursor?: number;
  isLoadingOlderHistory?: boolean;
  onLoadOlderHistory?: () => void;
}

export interface ChatThreadProps extends SharedChatThreadProps {
  events: AgentConversationEvent[];
}

/** Serves scroll-to-message requests from panes outside this tree (the Activity
 *  timeline). Sits inside `ChatMessageScrollerProvider` so it can fall back to the
 *  engine's `scrollToMessage`, which the windowed body's own jump replaces. */
function ThreadScrollRequestBridge({
  taskId,
  jumpToMessage,
  onFocusMessage,
  autoFollowRef,
}: {
  taskId?: string;
  jumpToMessage?: (id: string) => boolean;
  /** Marks the arrived-at message, so a jump from another pane lands as visibly as the
   *  keyboard's own. Without it the thread moves and nothing says where to. */
  onFocusMessage?: (id: string) => void;
  autoFollowRef?: RefObject<ThreadFollowState>;
}) {
  const { scrollToMessage } = useChatMessageScroller();
  const jump = jumpToMessage ?? scrollToMessage;
  const handleRequest = useCallback(
    (id: string) => {
      // A jump is the reader choosing a spot, so following lets go before the scroll rather
      // than in reaction to it: the scroll event that would release it arrives a frame late,
      // by which point following has already pulled the thread back down.
      if (autoFollowRef)
        autoFollowRef.current = { following: false, leftEnd: true };
      // Both jumps answer false while the target row is absent (from the element registry,
      // or from the row index), and the caller retries, so only claim the focus once the
      // thread actually moved.
      const landed = jump(id);
      if (landed) onFocusMessage?.(id);
      return landed;
    },
    [jump, onFocusMessage, autoFollowRef],
  );
  useThreadScrollRequest(taskId, handleRequest);
  return null;
}

export interface AcpChatThreadProps extends SharedChatThreadProps {
  events: AcpMessage[];
}

export function ChatThread({ events, ...props }: ChatThreadProps) {
  const { items, ...footerState } = useAgentConversationItems(
    events,
    props.isPromptPending,
  );

  return (
    <ChatThreadRenderer
      key={props.taskId}
      {...props}
      conversationItems={items}
      footerEvents={[]}
      footerState={footerState}
    />
  );
}

export function AcpChatThread({ events, ...props }: AcpChatThreadProps) {
  const showDebugLogs = useSettingsStore((state) => state.debugLogsCloudRuns);
  const { items } = useConversationItems(events, props.isPromptPending, {
    showDebugLogs,
  });

  return (
    <ChatThreadRenderer
      key={props.taskId}
      {...props}
      conversationItems={items}
      footerEvents={events}
    />
  );
}

interface ChatThreadRendererProps extends SharedChatThreadProps {
  conversationItems: ConversationItem[];
  footerEvents: AcpMessage[];
}

function ChatThreadRenderer({
  conversationItems,
  footerEvents,
  groupToolCalls = true,
  isPromptPending,
  promptStartedAt,
  repoPath,
  task,
  taskId,
  footerState,
  hasPendingPermission,
  promptRecallRef,
  olderHistoryCursor = 0,
  isLoadingOlderHistory,
  onLoadOlderHistory,
}: ChatThreadRendererProps) {
  const diffWorkerFactory = useService<DiffWorkerFactory>(DIFF_WORKER_FACTORY);
  const diffsPoolOptions = useMemo(
    () => ({
      workerFactory: () => diffWorkerFactory(),
      totalASTLRUCacheSize: 200,
    }),
    [diffWorkerFactory],
  );

  const optimisticItems = useOptimisticItemsForTask(taskId);
  const isCloud = useSessionIsCloud(taskId);

  const items = useMemo<ConversationItem[]>(
    () =>
      mergeConversationItems({ conversationItems, optimisticItems, isCloud }),
    [conversationItems, optimisticItems, isCloud],
  );

  const rows = useMemo<TurnRow[]>(
    () => groupIntoTurns(groupToolCalls ? groupToolRuns(items) : items),
    [items, groupToolCalls],
  );

  // Virtualization ratchet: past the threshold the thread switches to the windowed body and
  // stays there for the life of this mount (see CHAT_THREAD_VIRTUALIZATION_THRESHOLD). Long
  // sessions start virtualized from the first render; a live session flips once mid-stream,
  // resuming from the scroll state the non-virtualized body recorded.
  //
  // A pageable transcript is windowed however short it is: prepending older history shifts the
  // non-virtualized body's ordinal keys, which rebinds mounted rows to older content and loses the
  // reader's place (see {@link keyTurnRows}).
  const flatCount = useMemo(() => countFlatRows(rows), [rows]);
  const needsWindowing =
    flatCount > CHAT_THREAD_VIRTUALIZATION_THRESHOLD || olderHistoryCursor > 0;
  const [virtualized, setVirtualized] = useState(() => needsWindowing);
  if (!virtualized && needsWindowing) {
    setVirtualized(true);
  }
  const flatRows = useMemo(
    () => (virtualized ? flattenTurnRows(rows) : EMPTY_FLAT_ROWS),
    [virtualized, rows],
  );
  const threadResumeRef = useRef<ThreadScrollResume>({
    atBottom: true,
    anchorId: null,
  });

  const [jumpPickerOpen, setJumpPickerOpen] = useState(false);
  const [keyboardFocusedMessageId, setKeyboardFocusedMessageId] = useState<
    string | null
  >(null);
  const clearKeyboardFocus = useCallback(() => {
    setKeyboardFocusedMessageId(null);
  }, []);

  const renderItem = useCallback(
    (item: ConversationItem) => {
      switch (item.type) {
        // user_message is rendered by ThreadRow via UserBubble (it needs the active-anchor state for
        // the sticky header overlay), so the switch skips it here.
        case "user_message":
          return null;
        case "git_action":
          return <GitActionMessage actionType={item.actionType} />;
        case "skill_button_action":
          return <SkillButtonActionMessage buttonId={item.buttonId} />;
        case "session_update": {
          const update = item.update;
          // Assistant prose → start-aligned ghost bubble. Everything else (tool calls, thoughts,
          // console, status) keeps the existing renderer for now — ChatMarker mapping is next.
          if (
            update.sessionUpdate === "agent_message_chunk" &&
            update.content.type === "text"
          ) {
            return (
              <AgentProse
                text={update.content.text}
                isStreaming={!item.turnContext.turnComplete}
              />
            );
          }
          const rendered = (
            <SessionUpdateView
              item={item.update}
              toolCalls={item.turnContext.toolCalls}
              childItems={item.turnContext.childItems}
              turnCancelled={item.turnContext.turnCancelled}
              turnComplete={item.turnContext.turnComplete}
              thoughtComplete={item.thoughtComplete}
            />
          );
          return rendered;
        }
        case "git_action_result":
          return repoPath ? (
            <GitActionResult
              actionType={item.actionType}
              repoPath={repoPath}
              turnId={item.turnId}
            />
          ) : null;
        case "turn_cancelled":
          return (
            <ChatMarker variant="separator">
              <ChatMarkerContent>
                {item.interruptReason === "moving_to_worktree"
                  ? "Paused while worktree is focused"
                  : "Interrupted by user"}
              </ChatMarkerContent>
            </ChatMarker>
          );
        case "user_shell_execute":
          return <UserShellExecuteView item={item} />;
      }
    },
    [repoPath],
  );

  const footer = (
    <>
      <ChatThreadFooter
        events={footerEvents}
        isPromptPending={isPromptPending}
        promptStartedAt={promptStartedAt}
        task={task}
        taskId={taskId}
        footerState={footerState}
        hasPendingPermission={hasPendingPermission}
      />
    </>
  );

  const renderWindowedRow = useCallback(
    (row: FlatThreadRow) => (
      <FlatRowView
        row={row}
        renderItem={renderItem}
        keyboardFocused={row.item.id === keyboardFocusedMessageId}
      />
    ),
    [renderItem, keyboardFocusedMessageId],
  );

  // Lives here rather than in the plain body so a jump from another pane can drop the pin
  // before it scrolls.
  const autoFollowRef = useRef<ThreadFollowState>(FOLLOWING_END);

  // The nav layer sits beside the scroll body so it can be handed the windowed body's jump
  // implementation — the engine's `scrollToMessage` only reaches mounted rows.
  const renderNav = (jumpToMessage?: (id: string) => boolean) => (
    <>
      <ThreadKeyboardNav
        items={items}
        jumpPickerOpen={jumpPickerOpen}
        setJumpPickerOpen={setJumpPickerOpen}
        keyboardFocusedMessageId={keyboardFocusedMessageId}
        setKeyboardFocusedMessageId={setKeyboardFocusedMessageId}
        promptRecallRef={promptRecallRef}
        jumpToMessage={jumpToMessage}
      />
      <ThreadScrollRequestBridge
        taskId={taskId}
        jumpToMessage={jumpToMessage}
        onFocusMessage={setKeyboardFocusedMessageId}
        // Only the plain body needs it: the windowed body's own jump drops its pin.
        autoFollowRef={jumpToMessage ? undefined : autoFollowRef}
      />
    </>
  );

  return (
    <WorkerPoolContextProvider
      poolOptions={diffsPoolOptions}
      highlighterOptions={DIFFS_HIGHLIGHTER_OPTIONS}
    >
      <SessionTaskIdProvider taskId={taskId}>
        <ChatThreadChromeProvider value={true}>
          <ChatMessageScrollerProvider
            // The windowed body owns following itself (anchorTo end + followOnAppend) — the
            // engine's own follow would fight it, so it only auto-scrolls when non-virtualized.
            autoScroll={!virtualized}
            defaultScrollPosition="end"
            // `scrollEdgeThreshold` is left at the engine's tight default on purpose. The engine
            // re-enters "following-bottom" on *every* scroll event taken within the band, which
            // overrides the free-scrolling its own wheel handler just set — so a wide band traps a
            // reader scrolling up out of the bottom, and streamed content yanks them back each
            // frame. `ThreadAutoFollow` is what keeps the thread pinned across the band's width;
            // unlike the engine it only lets go on a real gesture.
            scrollPreviousItemPeek={SCROLL_PREVIOUS_ITEM_PEEK}
          >
            {virtualized ? (
              <VirtualThreadScrollBody
                items={items}
                flatRows={flatRows}
                renderRow={renderWindowedRow}
                onUserInteract={clearKeyboardFocus}
                footer={footer}
                renderNav={renderNav}
                resumeRef={threadResumeRef}
                olderHistoryCursor={olderHistoryCursor}
                isLoadingOlderHistory={isLoadingOlderHistory}
                onLoadOlderHistory={onLoadOlderHistory}
              />
            ) : (
              <>
                <ThreadScrollBody
                  autoFollowRef={autoFollowRef}
                  items={items}
                  rows={rows}
                  renderItem={renderItem}
                  keyboardFocusedMessageId={keyboardFocusedMessageId}
                  onUserInteract={clearKeyboardFocus}
                  footer={footer}
                  resumeStateRef={threadResumeRef}
                />
                {renderNav()}
              </>
            )}
          </ChatMessageScrollerProvider>
        </ChatThreadChromeProvider>
      </SessionTaskIdProvider>
    </WorkerPoolContextProvider>
  );
}
