/**
 * Vertical geometry for the inbox card ("tinder") view.
 *
 * The card view is the one inbox surface whose content does not scroll: the
 * deck and the swipe-hint row are statically positioned, so anything the
 * floating chrome overlaps is permanently unreadable rather than momentarily
 * faded. The list and archive views can happily let rows pass under the header
 * fade; the card view cannot.
 *
 * Every number here is consumed both by the component that *draws* a piece of
 * floating chrome and by the card view that has to *avoid* it, so the two
 * cannot drift apart.
 */

/**
 * Height of `FloatingInboxHeader`'s fade below the top safe-area inset.
 *
 * Note this is 20pt taller than the `insets.top + 60` content inset the
 * scrolling inbox views use: the header's controls end at `insets.top + 54`,
 * but its gradient keeps painting background over the next 26pt. A statically
 * placed card that only cleared the controls would still have its top edge
 * washed out — and the swipe stamps, which are rotated and therefore reach
 * ~13pt above their own box, sat right in that band.
 */
const HEADER_FADE_HEIGHT = 80;

/** Bottom edge of the header fade — the first y a static card may occupy. */
export function inboxHeaderFadeHeight(insetTop: number): number {
  return insetTop + HEADER_FADE_HEIGHT;
}

/** Gap between the bottom safe-area inset and the `InboxViewToggle` pill. */
export const VIEW_TOGGLE_BOTTOM_GAP = 16;

/** Pill height: a 20pt icon inside `py-3` (12pt top and bottom). */
const VIEW_TOGGLE_HEIGHT = 44;

/** Breathing room between the pill and whatever the card view puts above it. */
const VIEW_TOGGLE_CLEARANCE = 12;

/**
 * Space the card view must leave at the bottom so its lowest row — the swipe
 * hint — clears both the home indicator and the floating view-toggle pill.
 */
export function inboxCardViewBottomInset(insetBottom: number): number {
  return (
    insetBottom +
    VIEW_TOGGLE_BOTTOM_GAP +
    VIEW_TOGGLE_HEIGHT +
    VIEW_TOGGLE_CLEARANCE
  );
}
