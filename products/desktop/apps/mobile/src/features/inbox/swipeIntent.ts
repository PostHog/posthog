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
