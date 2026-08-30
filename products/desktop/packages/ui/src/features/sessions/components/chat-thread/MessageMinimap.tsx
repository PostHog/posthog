import { Check, LinkIcon } from "@phosphor-icons/react";
import {
  cn,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  useChatMessageScroller,
  useChatMessageScrollerVisibility,
} from "@posthog/quill";
import type { ConversationItem } from "@posthog/ui/features/sessions/components/buildConversationItems";
import { useCopyMessageLink } from "@posthog/ui/features/sessions/components/chat-thread/useCopyMessageLink";
import {
  OverflowTickerText,
  useOverflowTickerReveal,
} from "@posthog/ui/primitives/OverflowTickerText";
import { useCallback, useMemo, useRef, useState } from "react";

/** Ticks drawn in the collapsed rail. The tick window slides with the reading
 *  position so the current turn always has a tick, wherever it sits in the
 *  loaded history. */
const MAX_TICKS = 12;
const MAX_LABEL_LENGTH = 200;
/** Message length (chars) at which a tick reaches full width. */
const FULL_WIDTH_CHARS = 220;
const MIN_TICK_WIDTH_PCT = 34;

interface MinimapEntry {
  id: string;
  label: string;
  /** 34–100%: longer messages draw longer ticks, so the rail reads like a document minimap. */
  widthPct: number;
}

function truncate(text: string, maxLength: number): string {
  const singleLine = text.replace(/\n+/g, " ").trim();
  if (singleLine.length <= maxLength) return singleLine;
  return `${singleLine.slice(0, maxLength)}…`;
}

/**
 * One row of the expanded list. The message text is never statically clipped: it fades at the right
 * edge while idle and ticker-scrolls to its end on hover or keyboard focus, matching sidebar items.
 *
 * The row's trailing slot is a link affordance rather than the send time: what a reader wants from a
 * message they cannot scroll to together is a way to send it. It is a sibling of the menu item, not
 * a child, because the item itself renders a button and buttons do not nest — so it is laid over the
 * item's trailing padding, and a click on it never reaches the row's jump.
 */
function MinimapMenuItem({
  entry,
  isCurrent,
  itemRef,
  onSelect,
}: {
  entry: MinimapEntry;
  isCurrent: boolean;
  itemRef?: (node: HTMLElement | null) => void;
  onSelect: (id: string) => void;
}) {
  const { reveal, hoverProps, focusProps } = useOverflowTickerReveal();
  const { copied, copyLink } = useCopyMessageLink(entry.id);

  return (
    <div className="group/entry relative flex items-center">
      <DropdownMenuItem
        ref={itemRef}
        // The list is a navigation surface, not a one-shot command: clicking scrolls the thread and
        // leaves the menu up so the reader can keep hopping between turns.
        closeOnClick={false}
        onClick={() => onSelect(entry.id)}
        {...hoverProps}
        {...focusProps}
        data-selected={isCurrent || undefined}
        className={cn(
          "h-auto! min-h-7 flex-1 items-center py-1.5 text-left data-selected:bg-fill-selected data-selected:text-gray-12",
          copyLink && "pr-7",
        )}
      >
        <OverflowTickerText reveal={reveal} className="flex-1 text-[13px]">
          {entry.label}
        </OverflowTickerText>
      </DropdownMenuItem>
      {copyLink && (
        // Out of the tab order: Tab closes the menu, so the row stays the keyboard target and
        // copying is a pointer convenience.
        <button
          type="button"
          tabIndex={-1}
          aria-label="Copy link to this message"
          title={copied ? "Link copied" : "Copy link to this message"}
          onClick={copyLink}
          className="absolute right-1.5 flex items-center rounded p-0.5 text-(--gray-10) opacity-60 transition-opacity hover:opacity-100 group-hover/entry:opacity-100 motion-reduce:transition-none"
        >
          {copied ? <Check size={12} /> : <LinkIcon size={12} />}
        </button>
      )}
    </div>
  );
}

/**
 * Minimap of the user's turns, parked in the thread's top-right corner.
 *
 * Collapsed it is a small stack of ticks — one per user message, width scaled by message length.
 * Hovering or keyboard-focusing the rail opens the full list; picking an entry scrolls that message
 * into view and leaves the list open to jump again. Replaces the floating "jump to your message"
 * pill, which only ever offered the single anchored turn.
 *
 * Only this component subscribes to the scroller's per-scroll visibility state, so the message rows
 * never re-render as the highlight moves.
 */
export function MessageMinimap({
  items,
  onJump,
  anchorId,
}: {
  items: ConversationItem[];
  /**
   * Jump implementation for the windowed body, whose rows are mostly unmounted — the engine's
   * `scrollToMessage` only reaches rows that exist in the DOM. Omitted for the plain body.
   */
  onJump?: (id: string) => void;
  /**
   * Current turn for the windowed body, which tracks its own anchor — the engine's visibility state
   * only sees mounted rows. Omitted for the plain body.
   */
  anchorId?: string | null;
}) {
  const visibility = useChatMessageScrollerVisibility();
  const { scrollToMessage } = useChatMessageScroller();
  const jump = onJump ?? scrollToMessage;
  const currentAnchorId = anchorId ?? visibility.currentAnchorId;
  const [open, setOpen] = useState(false);
  // Base UI returns focus to the trigger when the menu closes. Without this guard the resulting
  // focus event would immediately re-open the menu the user just dismissed or selected from.
  const reopenBlockedUntil = useRef(0);

  const entries = useMemo<MinimapEntry[]>(() => {
    const result: MinimapEntry[] = [];
    for (const item of items) {
      if (item.type !== "user_message") continue;
      const fullText = item.content;
      const ratio = Math.min(1, fullText.trim().length / FULL_WIDTH_CHARS);
      result.push({
        id: item.id,
        label: truncate(fullText, MAX_LABEL_LENGTH),
        widthPct: MIN_TICK_WIDTH_PCT + (100 - MIN_TICK_WIDTH_PCT) * ratio,
      });
    }
    return result;
  }, [items]);

  const railEntries = useMemo<MinimapEntry[]>(() => {
    if (entries.length <= MAX_TICKS) return entries;
    const anchorIndex = entries.findIndex(
      (entry) => entry.id === currentAnchorId,
    );
    if (anchorIndex === -1) return entries.slice(-MAX_TICKS);
    const start = Math.min(
      Math.max(0, anchorIndex - Math.floor(MAX_TICKS / 2)),
      entries.length - MAX_TICKS,
    );
    return entries.slice(start, start + MAX_TICKS);
  }, [entries, currentAnchorId]);

  const handleOpenChange = useCallback((nextOpen: boolean) => {
    if (!nextOpen) reopenBlockedUntil.current = Date.now() + 250;
    setOpen(nextOpen);
  }, []);

  // The popup mounts on open, so this ref callback fires exactly when the list appears: bring the
  // turn the reader is currently parked on into view instead of opening at the oldest message.
  const activeItemRef = useCallback((node: HTMLElement | null) => {
    node?.scrollIntoView({ block: "nearest" });
  }, []);

  // One turn is not a map — there is nowhere to jump to.
  if (entries.length < 2) return null;

  return (
    // Hugs the scroll container's top-right corner (clear of the scrollbar). It floats over the
    // column rather than displacing it: translucent and blurred, and pointer-transparent except on
    // the trigger itself. Rows only pass underneath once the thread is too narrow for the column's
    // own slack to clear the rail's 44px.
    <div className="pointer-events-none absolute top-2 right-3 z-10">
      <DropdownMenu open={open} onOpenChange={handleOpenChange}>
        <DropdownMenuTrigger
          openOnHover
          // Short both ways: the list opens over the rail, so there is no travel to protect
          // against, and a lingering close reads as lag when you flick past.
          delay={50}
          closeDelay={30}
          aria-label={`Jump to one of your ${entries.length} messages`}
          // Keyboard focus expands too, matching hover. Guarded against the close-then-refocus loop.
          onFocus={(event) => {
            if (!event.currentTarget.matches(":focus-visible")) return;
            if (Date.now() < reopenBlockedUntil.current) return;
            setOpen(true);
          }}
          className={cn(
            "pointer-events-auto flex w-[32px] cursor-pointer flex-col items-end gap-[3px]",
            "rounded-md bg-(--color-background)/85 p-1.5 backdrop-blur-sm",
            "transition-colors duration-150 ease-out motion-reduce:transition-none",
            "hover:bg-(--gray-3) data-[popup-open]:bg-(--gray-3)",
            "focus-visible:outline-(--accent-8) focus-visible:outline-2 focus-visible:outline-offset-1",
          )}
        >
          {railEntries.map((entry) => (
            <span
              key={entry.id}
              aria-hidden="true"
              style={{ width: `${entry.widthPct}%` }}
              className={cn(
                "h-[2px] shrink-0 rounded-full transition-colors duration-150 ease-out motion-reduce:transition-none",
                entry.id === currentAnchorId
                  ? "bg-(--accent-9)"
                  : "bg-(--gray-8)",
              )}
            />
          ))}
        </DropdownMenuTrigger>

        <DropdownMenuContent
          // The list takes the rail's own top-right corner as its origin: pulling back by the
          // anchor's height lands the popup's top edge on the rail's top edge, so it expands in
          // place (down and to the left) rather than dropping below. It also means the popup opens
          // under the pointer, with no dead space to cross that would close a hover menu.
          align="end"
          side="bottom"
          sideOffset={({ anchor }) => -anchor.height}
          // Base UI derives the origin from the un-offset anchor edge; pin it to the shared corner
          // so the open animation scales out of the rail itself.
          className="max-h-[min(60vh,420px)] w-[320px] origin-top-right! overflow-y-auto"
        >
          {entries.map((entry) => (
            <MinimapMenuItem
              key={entry.id}
              entry={entry}
              isCurrent={entry.id === currentAnchorId}
              itemRef={entry.id === currentAnchorId ? activeItemRef : undefined}
              onSelect={jump}
            />
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}
