import { type DragOperation, Modifier } from "@dnd-kit/abstract";

/**
 * Vertical pointer travel, in px, that tears a dragged pill out of the strip.
 * One pill height, as in Chrome: a wobble while reordering stays in the lane,
 * a deliberate pull down (or up) detaches the pill.
 */
export const DETACH_DISTANCE = 24;

export function exceedsDetachDistance(dy: number): boolean {
  return Math.abs(dy) >= DETACH_DISTANCE;
}

/**
 * Holds a pill in the strip's row until the pointer has travelled far enough
 * to detach it. After that the pill follows the pointer freely, and it snaps
 * back into the row if the pointer returns. Keep it the pill's only modifier:
 * `transform` is the raw pointer delta for the first modifier in the chain,
 * and the position snapshot dnd-kit passes here carries no `delta`.
 */
export class DetachFromStrip extends Modifier {
  apply({ transform }: DragOperation) {
    return exceedsDetachDistance(transform.y)
      ? transform
      : { ...transform, y: 0 };
  }
}
