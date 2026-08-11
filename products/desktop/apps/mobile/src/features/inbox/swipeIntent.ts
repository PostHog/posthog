/**
 * Horizontal drag distance, in points, that commits a card swipe. Dragging a
 * card this far and letting go accepts (right) or dismisses (left) it.
 */
export const SWIPE_COMMIT_THRESHOLD = 120;

/**
 * Where the intent stamp starts to fade in. Below this the drag is still
 * plausibly a scroll or a wobble, and stamping it would be noise.
 */
export const SWIPE_INTENT_THRESHOLD = 40;

/**
 * Horizontal drag, in points, before the card claims the gesture from whatever
 * is underneath it.
 *
 * Larger than the 8pt the card used when nothing competed for the touch: the
 * card body scrolls now, and a vertical scroll that wobbles a few points
 * sideways must not fling the report off screen.
 */
export const HORIZONTAL_CLAIM_DX = 14;

/**
 * How much more horizontal than vertical a drag has to be to count as a swipe.
 * A plain `|dx| > |dy|` test hands 46° drags to the card, which is exactly
 * where a thumb dragging down a long summary lives.
 */
export const HORIZONTAL_CLAIM_RATIO = 1.6;

/**
 * Whether a drag is unambiguously a card swipe rather than a scroll of the
 * card's body.
 *
 * This is asked on the responder *capture* pass, so the card gets first refusal
 * on each move before the scroll view can claim it. The asymmetry is deliberate
 * and one-directional: a gesture that starts horizontally swipes, and a gesture
 * that has already started scrolling keeps scrolling until the finger lifts,
 * because a scroll view that has begun scrolling refuses to hand the responder
 * back. Nudging these numbers down trades card-swipe sensitivity for scroll
 * stability, not the other way around.
 */
export function shouldClaimHorizontalDrag(dx: number, dy: number): boolean {
  return (
    Math.abs(dx) > HORIZONTAL_CLAIM_DX &&
    Math.abs(dx) > Math.abs(dy) * HORIZONTAL_CLAIM_RATIO
  );
}

/** Right-swipe starts a task from the report; left-swipe dismisses it. */
export type SwipeIntent = "accept" | "dismiss";

export interface StampOpacityRange {
  inputRange: number[];
  outputRange: number[];
  extrapolate: "clamp";
}

/**
 * `Animated.Value.interpolate` config that fades a stamp in over the same
 * distance `stampOpacity` describes — the card drives opacity off the native
 * driver rather than re-rendering per frame, so the two have to agree by
 * construction.
 */
export function stampOpacityRange(intent: SwipeIntent): StampOpacityRange {
  return intent === "accept"
    ? {
        inputRange: [SWIPE_INTENT_THRESHOLD, SWIPE_COMMIT_THRESHOLD],
        outputRange: [0, 1],
        extrapolate: "clamp",
      }
    : {
        inputRange: [-SWIPE_COMMIT_THRESHOLD, -SWIPE_INTENT_THRESHOLD],
        outputRange: [1, 0],
        extrapolate: "clamp",
      };
}

/**
 * Opacity of an intent stamp at a given drag offset: nothing until the drag
 * clears the threshold, then linear up to fully opaque exactly where letting
 * go would commit the swipe. Dragging the other way leaves it at 0.
 */
export function stampOpacity(dx: number, intent: SwipeIntent): number {
  const distance = intent === "accept" ? dx : -dx;
  if (distance <= SWIPE_INTENT_THRESHOLD) return 0;
  if (distance >= SWIPE_COMMIT_THRESHOLD) return 1;
  return (
    (distance - SWIPE_INTENT_THRESHOLD) /
    (SWIPE_COMMIT_THRESHOLD - SWIPE_INTENT_THRESHOLD)
  );
}
