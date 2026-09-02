import {
  CHAT_CONTENT_MAX_WIDTH,
  CHAT_CONTENT_PADDING_INLINE,
} from "@posthog/ui/features/sessions/constants";

/** Widest ring the composer paints outside its border box (quill's 3px focus outline). */
const OUTLINE_BLEED = 4;

/**
 * Centers composer-slot content at the chat width (or compact padding).
 *
 * The composer reserves the same horizontal room as the thread's scroll
 * content and caps at the same width, so the two columns are identical at
 * every panel width rather than only once the panel is wide enough for the
 * full column. Padding on the capped box instead of around it would eat into
 * `CHAT_CONTENT_MAX_WIDTH` and leave the composer narrower than the messages.
 *
 * The gutter is a percentage of this box, and the thread's equivalent box sits
 * inside a scroller whose `scrollbar-gutter: stable` has already taken the
 * scrollbar's width off it. Without the same reservation here, the composer
 * centers on a wider box and its column lands half a scrollbar right of the
 * messages. Reserving it rather than subtracting a constant keeps the browser's
 * own measurement authoritative, since scrollbar width varies by platform.
 */
export function ComposerWidth({
  compact,
  children,
}: {
  compact: boolean;
  children: React.ReactNode;
}) {
  if (compact) {
    return <div className="p-1">{children}</div>;
  }

  return (
    <div
      style={{
        paddingInline: CHAT_CONTENT_PADDING_INLINE,
        overflow: "hidden",
        scrollbarGutter: "stable",
        // `overflow: hidden` clips at this box's padding edge, which sits flush
        // with the composer's top, so the focus ring painted outside its border
        // box would lose its top. Buy the ring room and take it back out of the
        // layout. The sides have the gutter and `pb-2` covers below.
        paddingBlockStart: OUTLINE_BLEED,
        marginBlockStart: -OUTLINE_BLEED,
      }}
    >
      <div
        className="mx-auto pb-2"
        style={{ maxWidth: CHAT_CONTENT_MAX_WIDTH }}
      >
        {children}
      </div>
    </div>
  );
}
