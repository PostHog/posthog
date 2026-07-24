import {
  CaretDown,
  ChatCircle,
  Check,
  Copy,
  FileText,
  Scroll,
} from "@phosphor-icons/react";
import { WorkerPoolContextProvider } from "@pierre/diffs/react";
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
  cn,
  useChatMessageScroller,
  useChatMessageScrollerScrollable,
  useChatMessageScrollerVisibility,
} from "@posthog/quill";
import type { AcpMessage, AgentConversationEvent } from "@posthog/shared";
import { PROJECT_BLUEBIRD_FLAG } from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import { SHORTCUTS } from "@posthog/ui/features/command/keyboard-shortcuts";
import { useSmoothedText } from "@posthog/ui/features/editor/components/useSmoothedText";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { usePanelLayoutStore } from "@posthog/ui/features/panels/panelLayoutStore";
import type { ConversationItem } from "@posthog/ui/features/sessions/components/buildConversationItems";
import { CloudArtifactDownloads } from "@posthog/ui/features/sessions/components/CloudArtifactDownloads";
import {
  ChatMarkdown,
  ChatStreamingMarkdown,
} from "@posthog/ui/features/sessions/components/chat-thread/ChatMarkdown";
import { ChatThreadFooter } from "@posthog/ui/features/sessions/components/chat-thread/ChatThreadFooter";
import { ChatThreadChromeProvider } from "@posthog/ui/features/sessions/components/chat-thread/chatThreadChrome";
import {
  PROMPT_RECALL_HINT_KEY,
  type PromptRecallHandler,
} from "@posthog/ui/features/sessions/components/chat-thread/composerPromptRecall";
import { MessageJumpPicker } from "@posthog/ui/features/sessions/components/chat-thread/MessageJumpPicker";
import {
  ToolGroup,
  type ToolGroupItem,
} from "@posthog/ui/features/sessions/components/chat-thread/ToolGroup";
import { THREAD_HOTKEY_OPTIONS } from "@posthog/ui/features/sessions/components/chat-thread/threadHotkeys";
import { usePromptRecallSource } from "@posthog/ui/features/sessions/components/chat-thread/usePromptRecallSource";
import { GitActionMessage } from "@posthog/ui/features/sessions/components/GitActionMessage";
import { GitActionResult } from "@posthog/ui/features/sessions/components/GitActionResult";
import { mergeConversationItems } from "@posthog/ui/features/sessions/components/mergeConversationItems";
import { extractCanvasInstructions } from "@posthog/ui/features/sessions/components/session-update/canvasInstructions";
import { extractChannelContext } from "@posthog/ui/features/sessions/components/session-update/channelContext";
import { extractCustomInstructions } from "@posthog/ui/features/sessions/components/session-update/customInstructions";
import {
  hasFileMentions,
  MentionChip,
  parseFileMentions,
} from "@posthog/ui/features/sessions/components/session-update/parseFileMentions";
import { SessionUpdateView } from "@posthog/ui/features/sessions/components/session-update/SessionUpdateView";
import { UserShellExecuteView } from "@posthog/ui/features/sessions/components/session-update/UserShellExecuteView";
import { UserMessageAttachments } from "@posthog/ui/features/sessions/components/UserMessageAttachments";
import { CHAT_CONTENT_MAX_WIDTH } from "@posthog/ui/features/sessions/constants";
import { DIFFS_HIGHLIGHTER_OPTIONS } from "@posthog/ui/features/sessions/diffHighlighterOptions";
import { useAgentConversationItems } from "@posthog/ui/features/sessions/hooks/useAgentConversationItems";
import { useConversationItems } from "@posthog/ui/features/sessions/hooks/useConversationItems";
import {
  useOptimisticItemsForTask,
  useSessionIsCloud,
} from "@posthog/ui/features/sessions/sessionStore";
import type { UserMessageAttachment } from "@posthog/ui/features/sessions/userMessageTypes";
import {
  SessionTaskIdProvider,
  useSessionTaskId,
} from "@posthog/ui/features/sessions/useSessionTaskId";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { SkillButtonActionMessage } from "@posthog/ui/features/skill-buttons/components/SkillButtonActionMessage";
import { useCopy } from "@posthog/ui/primitives/useCopy";
import {
  DIFF_WORKER_FACTORY,
  type DiffWorkerFactory,
} from "@posthog/ui/shell/diffWorkerHost";
import { IconButton, Tooltip } from "@radix-ui/themes";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import {
  memo,
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

/** A row is either a parsed conversation item or a synthesized group of tool calls. */
type ThreadItem = ConversationItem | ToolGroupItem;

/**
 * A contiguous run of non-user rows (assistant prose, tools, git actions, ...) shown as one
 * `bg-muted/30` block with tight internal spacing. Broken only by a user message.
 */
type AgentTurn = { type: "agent_turn"; id: string; items: ThreadItem[] };

/** Top-level row: a standalone user message, or a grouped agent turn. */
type TurnRow = ThreadItem | AgentTurn;

type SessionUpdateItem = Extract<ConversationItem, { type: "session_update" }>;

function isToolCallItem(item: ConversationItem): item is SessionUpdateItem {
  return (
    item.type === "session_update" && item.update.sessionUpdate === "tool_call"
  );
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
 * Collapse each contiguous run of ≥2 tool-call updates into a single `ToolGroupItem`. A run is
 * broken by any *visible* non-tool item (prose, thought, status) so groups follow reading order;
 * invisible updates (see {@link INVISIBLE_UPDATES}) are transparent and don't split a run. A lone
 * tool call passes through untouched — it stays a single marker, matching the legacy thread.
 */
function groupToolRuns(items: ConversationItem[]): ThreadItem[] {
  const out: ThreadItem[] = [];
  // The buffer holds the active run: tool items plus any invisible items interleaved with them.
  let buffer: ConversationItem[] = [];
  let toolCount = 0;

  const flush = () => {
    if (toolCount >= 2) {
      const tools = buffer.filter(isToolCallItem);
      out.push({ type: "tool_group", id: tools[0].id, tools });
    } else {
      out.push(...buffer);
    }
    buffer = [];
    toolCount = 0;
  };

  for (const item of items) {
    if (isToolCallItem(item)) {
      buffer.push(item);
      toolCount++;
    } else if (isInvisibleItem(item)) {
      // Don't break the run; carry it along (it renders nothing wherever it lands).
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
 * the agent's successive replies and tool calls.
 */
function groupIntoTurns(rows: ThreadItem[]): TurnRow[] {
  const out: TurnRow[] = [];
  let buffer: ThreadItem[] = [];
  const flush = () => {
    if (buffer.length > 0) {
      out.push({ type: "agent_turn", id: buffer[0].id, items: buffer });
      buffer = [];
    }
  };
  for (const row of rows) {
    // git_action and skill_button_action stand in for the user's message when the prompt was a
    // git operation or a skill button click (see handlePromptRequest) — they open a turn just
    // like a user message, so they break the agent card too rather than render inside it as if
    // they were agent output. Same boundary set as the legacy view's buildThreadGroups.
    if (
      row.type === "user_message" ||
      row.type === "git_action" ||
      row.type === "skill_button_action"
    ) {
      flush();
      out.push(row);
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
 * Hover-revealed timestamp rendered right-aligned under agent-side content (the end-aligned user
 * bubble keeps its own right-aligned footer). Sits inside a `group` container so it fades in only
 * while that container is hovered. Shown once per completed agent turn (under the turn card)
 * rather than on every message — per-row it was too noisy.
 */
function RowTimestamp({ timestamp }: { timestamp?: number }) {
  if (timestamp == null) return null;
  return (
    <ChatMessageFooter className="mt-2 items-center justify-end gap-1 pl-0 opacity-0 transition-opacity group-hover:opacity-100">
      <span className="text-muted-foreground">
        {formatTimestamp(timestamp)}
      </span>
    </ChatMessageFooter>
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
  const channelContext = useMemo(
    () => extractChannelContext(content),
    [content],
  );
  const afterChannelContext = channelContext
    ? channelContext.stripped
    : content;
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
  const displayContent = customInstructions
    ? customInstructions.stripped
    : afterCanvasInstructions;
  const showChannelContextTag = !!channelContext && bluebirdEnabled;
  const showCanvasInstructionsTag = !!canvasInstructions && bluebirdEnabled;
  const showHeaderChips = showChannelContextTag || showCanvasInstructionsTag;
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
    <ChatMessage align="end" className="group">
      <ChatMessageContent className="gap-1 pr-9">
        {showHeaderChips && (
          <ChatMessageHeader className="flex-wrap gap-1">
            {showChannelContextTag && channelContext && (
              <MentionChip
                icon={<FileText size={12} />}
                label={`${
                  channelContext.mention.name
                    ? `#${channelContext.mention.name} `
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
        <ChatBubble
          align="end"
          variant="default"
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
        {timestamp != null && (
          <ChatMessageFooter className="opacity-0 transition-opacity group-hover:opacity-100">
            {formatTimestamp(timestamp)}
          </ChatMessageFooter>
        )}
      </ChatMessageContent>
      <MessageCopyButton
        value={displayContent}
        revealClassName="group-hover:opacity-100"
      />
    </ChatMessage>
  );
}

/**
 * Copy icon that floats into a message's right rail on hover. The hover-group qualifier differs by
 * message type (`group` for user bubbles, `group/msg` for agent prose), so callers pass their own
 * `revealClassName` (the `group-hover*:opacity-100` utility).
 */
function MessageCopyButton({
  value,
  revealClassName,
}: {
  value: string;
  revealClassName: string;
}) {
  const { copied, copy } = useCopy();
  return (
    <Tooltip content={copied ? "Copied!" : "Copy message"}>
      <IconButton
        size="1"
        variant="ghost"
        color={copied ? "green" : "gray"}
        onClick={() => copy(value)}
        className={cn(
          "absolute top-1 right-1 cursor-pointer opacity-0 transition-opacity",
          revealClassName,
        )}
        aria-label="Copy message"
      >
        {copied ? <Check size={14} /> : <Copy size={14} />}
      </IconButton>
    </Tooltip>
  );
}

/**
 * "Fake sticky" header. A real `position: sticky` row can't hand off in this flat list (every row
 * shares one containing block, so they'd pile at the top) and sticking causes reflow. Instead we
 * overlay a single header, out of flow, pinned over the viewport top — showing the current turn's
 * user message (the engine's anchor) once the real one has scrolled off. Click to scroll back to it.
 *
 * Only this small component subscribes to the engine's per-scroll visibility state, so the rows
 * themselves never re-render on scroll.
 */
function StickyHeaderOverlay({ items }: { items: ConversationItem[] }) {
  const { currentAnchorId } = useChatMessageScrollerVisibility();
  const { scrollToMessage } = useChatMessageScroller();
  const shouldReduceMotion = useReducedMotion();
  const [dismissedId, setDismissedId] = useState<string | null>(null);
  const [offscreen, setOffscreen] = useState(false);
  // Anchor element used only to locate the enclosing scroller/viewport in the DOM.
  const probeRef = useRef<HTMLSpanElement>(null);

  const active = items.find(
    (i): i is Extract<ConversationItem, { type: "user_message" }> =>
      i.id === currentAnchorId && i.type === "user_message",
  );
  const activeId = active?.id ?? null;

  // The engine's `visibleMessageIds` can't be used here: its IntersectionObserver excludes a band of
  // `scrollPreviousItemPeek` px at the viewport top, which is exactly where a freshly-anchored turn
  // message lands — so it reads as "not visible" while plainly on screen. Measure real geometry
  // instead: the message is off-screen only once its bottom scrolls above the viewport top.
  useEffect(() => {
    // No reset when there's no anchor: the overlay render already guards on `active != null`, so a
    // stale `offscreen` is never shown, and a fresh anchor re-measures synchronously below. (Avoids
    // the prop-sync-in-effect pattern react-doctor flags.)
    if (activeId == null) return;
    const viewport = probeRef.current
      ?.closest('[data-slot="chat-message-scroller"]')
      ?.querySelector('[data-slot="chat-message-scroller-viewport"]');
    if (!viewport) return;

    const measure = () => {
      const el = viewport.querySelector(
        `[data-message-id="${CSS.escape(activeId)}"]`,
      );
      if (!el) {
        setOffscreen(false);
        return;
      }
      const messageBottom = el.getBoundingClientRect().bottom;
      const viewportTop = viewport.getBoundingClientRect().top;
      setOffscreen(messageBottom <= viewportTop + 4);
    };

    measure();
    viewport.addEventListener("scroll", measure, { passive: true });
    return () => viewport.removeEventListener("scroll", measure);
  }, [activeId]);

  // Once the real message is back on screen, clear the dismissal so the header can return later.
  useEffect(() => {
    if (!offscreen) setDismissedId(null);
  }, [offscreen]);

  const dismiss = (id: string) => {
    // Hide immediately on click (don't wait for the scroll to bring the message into view), then
    // jump to it.
    setDismissedId(id);
    scrollToMessage(id);
  };

  return (
    <>
      <span ref={probeRef} className="hidden" aria-hidden="true" />
      <AnimatePresence>
        {active != null && offscreen && active.id !== dismissedId && (
          <motion.div
            key="chat-sticky-header"
            // Slide in slightly from the top + fade (ease-out-cubic). Exit a touch faster.
            initial={shouldReduceMotion ? false : { opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={
              shouldReduceMotion
                ? { opacity: 0 }
                : { opacity: 0, y: -8, transition: { duration: 0.15 } }
            }
            transition={{ duration: 0.2, ease: [0.215, 0.61, 0.355, 1] }}
            // pointer-events-none on the strip so only the button catches clicks — the rest stays
            // transparent to the content scrolling underneath.
            className="pointer-events-none absolute inset-x-0 top-2 z-10"
          >
            {/* Align to the content column's right edge (matches the message rows) rather than the
                viewport edge, so the button reads in-context with the conversation. */}
            <div
              className="mx-auto flex w-full justify-end px-2"
              style={{ maxWidth: CHAT_CONTENT_MAX_WIDTH }}
            >
              <Button
                type="button"
                variant="outline"
                size="icon"
                title="Jump to your message"
                aria-label="Jump to your message"
                onClick={() => dismiss(active.id)}
                className="pointer-events-auto rounded-full bg-background shadow-md"
              >
                <ChatCircle />
              </Button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
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
    <ChatMessage align="start" className="group/msg">
      <ChatMessageContent className="gap-1 pr-9">
        <ChatBubble variant="ghost">
          <ChatBubbleContent>
            {isStreaming ? (
              <ChatStreamingMarkdown content={smoothed} />
            ) : (
              <ChatMarkdown content={text} />
            )}
          </ChatBubbleContent>
        </ChatBubble>
      </ChatMessageContent>
      {isStreaming ? null : (
        <MessageCopyButton
          value={text}
          revealClassName="group-hover/msg:opacity-100"
        />
      )}
    </ChatMessage>
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
    const context = item.tools[0]?.turnContext;
    const turnStreaming =
      !!context && !context.turnComplete && !context.turnCancelled;
    return (
      <ToolGroup
        tools={item.tools}
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
 * Completion time of an agent turn, taken from its last session-update item (tool groups count by
 * their last tool). Undefined while the turn is still streaming — the timestamp only appears once
 * the whole turn is done.
 */
function completedTurnTimestamp(turn: AgentTurn): number | undefined {
  for (let i = turn.items.length - 1; i >= 0; i--) {
    const item = turn.items[i];
    const last = item.type === "tool_group" ? item.tools.at(-1) : item;
    if (last?.type !== "session_update") continue;
    return last.turnContext.turnComplete ? last.timestamp : undefined;
  }
  return undefined;
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
        className="group mx-auto w-full px-4 empty:hidden"
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
        <RowTimestamp timestamp={completedTurnTimestamp(item)} />
      </ChatMessageScrollerItem>
    );
  }
  return (
    <ChatMessageScrollerItem
      messageId={item.id}
      scrollAnchor={item.type === "user_message"}
      className="mx-auto w-full px-2.5 py-1 empty:hidden"
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
 * Keeps the view pinned to the bottom from prompt submit until the user scrolls away.
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
 * User scroll intent (wheel, touch, pointer, keys — same signals the engine listens to) disarms
 * the pin; the next submit or the scroll-to-bottom button re-engages following.
 */
function ThreadAutoFollow({ items }: { items: ConversationItem[] }) {
  const { scrollToEnd } = useChatMessageScroller();
  const { end } = useChatMessageScrollerScrollable();
  const lastItem = items.at(-1);
  const userMessageCount = useMemo(
    () =>
      items.reduce((n, item) => (item.type === "user_message" ? n + 1 : n), 0),
    [items],
  );
  const prevCountRef = useRef(userMessageCount);
  const armedRef = useRef(false);
  const probeRef = useRef<HTMLSpanElement>(null);

  useLayoutEffect(() => {
    const previous = prevCountRef.current;
    prevCountRef.current = userMessageCount;
    if (previous === 0 || userMessageCount <= previous) return;
    if (lastItem?.type !== "user_message") return;
    armedRef.current = true;
    scrollToEnd({ behavior: "auto" });
  }, [userMessageCount, lastItem, scrollToEnd]);

  useEffect(() => {
    const viewport = probeRef.current
      ?.closest('[data-slot="chat-message-scroller"]')
      ?.querySelector('[data-slot="chat-message-scroller-viewport"]');
    if (!viewport) return;
    const disarm = () => {
      armedRef.current = false;
    };
    const events = ["wheel", "touchmove", "pointerdown", "keydown"] as const;
    for (const event of events) {
      viewport.addEventListener(event, disarm, { passive: true });
    }
    return () => {
      for (const event of events) {
        viewport.removeEventListener(event, disarm);
      }
    };
  }, []);

  // biome-ignore lint/correctness/useExhaustiveDependencies: re-check on every streamed change — `end` alone doesn't re-notify while it stays true across commits.
  useEffect(() => {
    if (armedRef.current && end) {
      scrollToEnd({ behavior: "auto" });
    }
  }, [items, end, scrollToEnd]);

  return <span ref={probeRef} className="hidden" aria-hidden="true" />;
}

/**
 * Keyboard message navigation (Alt/Option+Up/Down) and the Cmd/Ctrl+J jump picker. Rendered inside
 * `ChatMessageScrollerProvider` so it can call `scrollToMessage` from the engine — the same primitive
 * `StickyHeaderOverlay` uses to jump back to the anchored turn.
 */
function ThreadKeyboardNav({
  items,
  jumpPickerOpen,
  setJumpPickerOpen,
  keyboardFocusedMessageId,
  setKeyboardFocusedMessageId,
  promptRecallRef,
}: {
  items: ConversationItem[];
  jumpPickerOpen: boolean;
  setJumpPickerOpen: (value: boolean | ((prev: boolean) => boolean)) => void;
  keyboardFocusedMessageId: string | null;
  setKeyboardFocusedMessageId: (id: string | null) => void;
  promptRecallRef?: RefObject<PromptRecallHandler | null>;
}) {
  const { scrollToMessage } = useChatMessageScroller();

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

      useSettingsStore.getState().markHintLearned(PROMPT_RECALL_HINT_KEY);
      setKeyboardFocusedMessageId(nextId);
      scrollToMessage(nextId);
    },
    [
      keyboardFocusedMessageId,
      userMessageIds,
      setKeyboardFocusedMessageId,
      scrollToMessage,
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
      scrollToMessage(id);
    },
    [scrollToMessage, setKeyboardFocusedMessageId],
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

/** The scroll body, under the Provider so the overlay + scroll-button hooks can read engine state. */
function ThreadScrollBody({
  items,
  rows,
  renderItem,
  footer,
  keyboardFocusedMessageId,
  onUserInteract,
}: {
  items: ConversationItem[];
  rows: TurnRow[];
  renderItem: (item: ConversationItem) => ReactNode;
  /** Status row (duration / context usage) pinned as the last item in the thread. */
  footer?: ReactNode;
  keyboardFocusedMessageId?: string | null;
  /** Clears keyboard-focused message state on any pointer interaction with the thread. */
  onUserInteract?: () => void;
}) {
  const keyedRows = useMemo(() => {
    let userTurn = 0;
    return rows.map((item) => ({
      item,
      key: item.type === "user_message" ? `user-turn-${userTurn++}` : item.id,
    }));
  }, [rows]);

  // `group/thread` so the footer's hover-reveal (opacity-50 → 100 on group-hover) tracks the thread,
  // mirroring the legacy ConversationView container.
  return (
    <ChatMessageScroller
      className="group/thread"
      onPointerDownCapture={onUserInteract}
    >
      <StickyHeaderOverlay items={items} />
      <ThreadAutoFollow items={items} />
      <ChatMessageScrollerViewport>
        <ChatMessageScrollerContent
          className="gap-4 py-4 pb-8"
          density="default"
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
      <ChatMessageScrollerButton />
    </ChatMessageScroller>
  );
}

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
  isPromptPending: boolean | null;
  promptStartedAt?: number | null;
  promptRecallRef?: RefObject<PromptRecallHandler | null>;
  repoPath?: string | null;
  task?: Task;
  taskId?: string;
}

export interface ChatThreadProps extends SharedChatThreadProps {
  events: AgentConversationEvent[];
}

export interface AcpChatThreadProps extends SharedChatThreadProps {
  events: AcpMessage[];
}

export function ChatThread({ events, ...props }: ChatThreadProps) {
  const { items } = useAgentConversationItems(events, props.isPromptPending);

  return (
    <ChatThreadRenderer
      {...props}
      conversationItems={items}
      footerEvents={[]}
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
  isPromptPending,
  promptStartedAt,
  repoPath,
  task,
  taskId,
  promptRecallRef,
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
    () => groupIntoTurns(groupToolRuns(items)),
    [items],
  );

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

  return (
    <WorkerPoolContextProvider
      poolOptions={diffsPoolOptions}
      highlighterOptions={DIFFS_HIGHLIGHTER_OPTIONS}
    >
      <SessionTaskIdProvider taskId={taskId}>
        <ChatThreadChromeProvider value={true}>
          <ChatMessageScrollerProvider
            autoScroll
            defaultScrollPosition="end"
            // Default is 8px: with the thread's bottom padding you're rarely that close, so
            // auto-follow ("following-bottom") would disengage on any stray trackpad wheel and
            // never re-engage. Within this band the engine recaptures follow on the next content
            // change; deliberate upward flicks travel past it and stay free-scrolling.
            scrollEdgeThreshold={100}
            scrollPreviousItemPeek={64}
          >
            <ThreadScrollBody
              items={items}
              rows={rows}
              renderItem={renderItem}
              keyboardFocusedMessageId={keyboardFocusedMessageId}
              onUserInteract={clearKeyboardFocus}
              footer={
                <>
                  <CloudArtifactDownloads taskId={taskId} task={task} />
                  <ChatThreadFooter
                    events={footerEvents}
                    isPromptPending={isPromptPending}
                    promptStartedAt={promptStartedAt}
                    task={task}
                    taskId={taskId}
                  />
                </>
              }
            />
            <ThreadKeyboardNav
              items={items}
              jumpPickerOpen={jumpPickerOpen}
              setJumpPickerOpen={setJumpPickerOpen}
              keyboardFocusedMessageId={keyboardFocusedMessageId}
              setKeyboardFocusedMessageId={setKeyboardFocusedMessageId}
              promptRecallRef={promptRecallRef}
            />
          </ChatMessageScrollerProvider>
        </ChatThreadChromeProvider>
      </SessionTaskIdProvider>
    </WorkerPoolContextProvider>
  );
}
