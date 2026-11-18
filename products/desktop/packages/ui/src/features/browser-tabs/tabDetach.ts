import { type DragOperation, Modifier } from "@dnd-kit/abstract";

export const DETACH_DISTANCE = 24;

export function exceedsDetachDistance(dy: number): boolean {
  return Math.abs(dy) >= DETACH_DISTANCE;
}

export class DetachFromStrip extends Modifier {
  apply({ transform }: DragOperation) {
    return exceedsDetachDistance(transform.y)
      ? transform
      : { ...transform, y: 0 };
  }
}
