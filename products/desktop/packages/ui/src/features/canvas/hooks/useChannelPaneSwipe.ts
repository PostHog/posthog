import type { RefObject } from "react";
import { useEffect } from "react";

/** How far a horizontal gesture has to travel before it counts as a swipe. */
const SWIPE_THRESHOLD_PX = 45;
/** A pause this long ends the gesture, so momentum can't chain two swipes. */
const GESTURE_GAP_MS = 180;

/**
 * Two-finger horizontal swipes over the sidebar, mapped to the pane slider.
 *
 * A trackpad swipe arrives as a `wheel` event carrying `deltaX`; the sidebar has
 * nothing to scroll sideways, so we claim those and translate them into the
 * same back/forward the back row and a channel click already do. Swipe right
 * (the platform "back" direction, a negative `deltaX`) goes out to the list;
 * swipe left goes back into the channel you're still scoped to.
 *
 * Distance is accumulated across the event stream rather than read off a single
 * event — one flick is dozens of small deltas. Once a swipe fires, the gesture
 * is locked until the wheel goes quiet, so the momentum tail doesn't bounce the
 * panes back and forth.
 */
export function useChannelPaneSwipe(
  ref: RefObject<HTMLElement | null>,
  {
    enabled,
    onBack,
    onForward,
  }: { enabled: boolean; onBack: () => void; onForward: () => void },
): void {
  useEffect(() => {
    const element = ref.current;
    if (!element || !enabled) return;

    let travelled = 0;
    let lastEventAt = Number.NEGATIVE_INFINITY;
    let locked = false;

    const onWheel = (event: WheelEvent) => {
      // A mostly-vertical wheel is someone scrolling the list, not swiping.
      if (Math.abs(event.deltaX) <= Math.abs(event.deltaY)) return;
      // Claim it before anything upstream reads it as history navigation.
      event.preventDefault();

      if (event.timeStamp - lastEventAt > GESTURE_GAP_MS) {
        travelled = 0;
        locked = false;
      }
      lastEventAt = event.timeStamp;
      if (locked) return;

      travelled += event.deltaX;
      if (travelled <= -SWIPE_THRESHOLD_PX) {
        locked = true;
        onBack();
      } else if (travelled >= SWIPE_THRESHOLD_PX) {
        locked = true;
        onForward();
      }
    };

    element.addEventListener("wheel", onWheel, { passive: false });
    return () => element.removeEventListener("wheel", onWheel);
  }, [ref, enabled, onBack, onForward]);
}
