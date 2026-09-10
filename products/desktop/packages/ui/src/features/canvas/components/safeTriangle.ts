/**
 * The "safe triangle": the corridor a pointer is allowed to cross on its way
 * from the row it is on to the card that row opened.
 *
 * Base UI's `PreviewCard.Trigger` already runs floating-ui's `safePolygon`
 * inside itself, so cutting the corner toward the card does not *close* it.
 * The half it can't do is stop the rows under that diagonal from taking the
 * card off you: triggers sharing one handle swap the card with no delay — the
 * thing that makes sliding down a list feel like one card moving — so a run at
 * the card from the dot at a row's left edge lands on whichever row the pointer
 * clipped on the way out. floating-ui answers that with `safePolygon`'s
 * `blockPointerEvents`; `PreviewCard.Trigger` hard-codes `safePolygon()` and
 * exposes neither the option nor the polygon, and Base UI does not publish its
 * vendored copy of floating-ui. So this file is that one missing half, built to
 * the same quadrilateral, and nothing else.
 *
 * It holds a `mouseenter` back rather than blanking `pointer-events` across the
 * list, which is the other half of floating-ui's answer. Nothing is mutated:
 * the rows stay live, so a click that lands mid-traverse still opens the row it
 * hit rather than falling through a shielded list.
 */

/**
 * Rows are the elements this marks; everything else the pointer crosses is
 * scenery. Written on the row in `ChannelItemHoverCard`, read only here.
 */
export const PREVIEW_TRIGGER_SELECTOR = "[data-preview-card-trigger]";

/**
 * Half the height of the corridor where it starts, at the point the pointer
 * left the row, and equally the radius of the blind spot around that point.
 *
 * The two are one measurement because they are one fact. A pointer crosses
 * from one row to the next inside a single mouse sample, so the row's
 * `pointerleave` and the next row's `mouseenter` carry one position between
 * them: everything this close to the exit belongs to both a run at the card
 * and a step down the list, and the corridor is asked about the heading there
 * instead of about the position.
 */
const EXIT_BUFFER = 4;

/**
 * How long a held row waits before the pointer resting on it counts as an
 * answer.

 */
const HOLD_MS = 100;

const HEADING_STEP = 24;

interface Point {
  x: number;
  y: number;
}

/** Does the ray straight down from `point` cross the segment `a`→`b`? */
function crossesEdge(point: Point, a: Point, b: Point): boolean {
  return (
    a.y >= point.y !== b.y >= point.y &&
    point.x <= ((b.x - a.x) * (point.y - a.y)) / (b.y - a.y) + a.x
  );
}

/** Even-odd crossing test over a quadrilateral's four edges, in order. */
function isInsideQuadrilateral(point: Point, corners: Point[]): boolean {
  let inside = false;
  for (let i = 0; i < corners.length; i += 1) {
    if (crossesEdge(point, corners[i], corners[(i + 1) % corners.length])) {
      inside = !inside;
    }
  }
  return inside;
}

function isInsideRect(point: Point, rect: DOMRect): boolean {
  return (
    point.x >= rect.left &&
    point.x <= rect.right &&
    point.y >= rect.top &&
    point.y <= rect.bottom
  );
}

/**
 * Is the pointer still on its way from `exit` to `card`?

 *
 * The near edge is picked rather than assumed: these cards open on the row's
 * right, but a card near the screen's right edge is flipped to the left, and a
 * corridor pointing the wrong way would guard nothing.
 */
export function isInSafeTriangle(
  point: Point,
  exit: Point,
  card: DOMRect,
): boolean {
  const nearEdgeX = card.left >= exit.x ? card.left : card.right;
  return isInsideQuadrilateral(point, [
    { x: exit.x, y: exit.y + EXIT_BUFFER },
    { x: exit.x, y: exit.y - EXIT_BUFFER },
    { x: nearEdgeX, y: card.top },
    { x: nearEdgeX, y: card.bottom },
  ]);
}

function isAtExit(point: Point, exit: Point): boolean {
  return (
    Math.abs(point.x - exit.x) <= EXIT_BUFFER &&
    Math.abs(point.y - exit.y) <= EXIT_BUFFER
  );
}

/**
 * One step further along the way the pointer is going, at a fixed length so
 * that a slow gesture and a fast one in the same direction read the same.
 */
function stepAhead(point: Point, heading: Point): Point {
  const length = Math.hypot(heading.x, heading.y);
  return {
    x: point.x + (heading.x / length) * HEADING_STEP,
    y: point.y + (heading.y / length) * HEADING_STEP,
  };
}

export interface SafeTriangleGuard {
  /**
   * The pointer has just left `trigger` at (`x`, `y`) with `card` open beside
   * it. Until it arrives, turns back, or leaves the corridor, no other row may
   * take the card.
   */
  arm(options: { trigger: Element; card: Element; x: number; y: number }): void;
  /** Stop guarding, because the card is gone. Hands back any held row. */
  release(): void;
  /** Stop guarding and hand nothing back. Safe to call while unarmed. */
  disarm(): void;
  destroy(): void;
}

export function createSafeTriangleGuard(): SafeTriangleGuard {
  interface Run {
    trigger: Element;
    card: Element;
    exit: Point;
    /** The row whose `mouseenter` was held back, and where the pointer was. */
    held: Element | null;
    at: Point;
    heading: Point | null;
    settling: ReturnType<typeof setTimeout> | undefined;
  }
  let run: Run | null = null;

  let previous: Point | null = null;
  let latest: Point | null = null;

  function heading(from: Point | null, to: Point | null): Point | null {
    if (!from || !to) {
      return null;
    }
    const step = { x: to.x - from.x, y: to.y - from.y };
    return step.x === 0 && step.y === 0 ? null : step;
  }
  document.addEventListener("pointermove", trackPointer);

  function onSettled(): void {
    if (!run) {
      return;
    }
    if (run.held && isInsideRect(run.at, run.held.getBoundingClientRect())) {
      release();
      return;
    }
    run.held = null;
  }

  function holdUntilSettled(): void {
    if (!run) {
      return;
    }
    clearTimeout(run.settling);
    run.settling = setTimeout(onSettled, HOLD_MS);
  }

  function isOnTheRun(at: Point): boolean {
    if (!run) {
      return false;
    }
    const card = run.card.getBoundingClientRect();
    if (!isAtExit(at, run.exit)) {
      return isInSafeTriangle(at, run.exit, card);
    }
    if (!run.heading) {
      return true;
    }
    return isInSafeTriangle(stepAhead(at, run.heading), run.exit, card);
  }

  /**
   * Capture, on the document, so this runs before the listener Base UI puts on
   * the row itself. `mouseenter` doesn't bubble, but it is still dispatched
   * down the ancestor chain, so stopping it here means the row never hears it.
   */
  function onEnterCapture(event: Event): void {
    if (!run || !(event.target instanceof Element)) {
      return;
    }
    // Arrived. The card looks after itself from here.
    if (run.card.contains(event.target)) {
      disarm();
      return;
    }
    const row = event.target.closest(PREVIEW_TRIGGER_SELECTOR);
    if (!row) {
      return;
    }
    // Back on the row we started from: there is nothing left to protect.
    if (row === run.trigger) {
      disarm();
      return;
    }
    const { clientX, clientY } = event as MouseEvent;
    const at = { x: clientX, y: clientY };
    // Already off the corridor as the row is met: the pointer wants this row
    // and not the card, and nothing has been taken from it yet to give back.
    if (!isOnTheRun(at)) {
      disarm();
      return;
    }
    run.held = row;
    run.at = at;
    holdUntilSettled();
    event.stopPropagation();
  }

  function trackPointer(event: Event): void {
    const { clientX, clientY } = event as MouseEvent;
    previous = latest;
    latest = { x: clientX, y: clientY };
    if (!run) {
      return;
    }
    run.at = latest;
    run.heading = heading(previous, latest);
    if (!isOnTheRun(run.at)) {
      release();
    }
  }

  function detach(): void {
    document.removeEventListener("mouseenter", onEnterCapture, true);
  }

  function disarm(): void {
    if (!run) {
      return;
    }
    clearTimeout(run.settling);
    run = null;
    detach();
  }

  function release(): void {
    const held = run?.held;
    const at = run?.at;
    disarm();
    // A row whose `mouseenter` was held back never got another one — the
    // pointer is inside it, and `mouseenter` only fires on the way in. So if
    // the card went while the pointer was still resting there, that row is
    // owed the event, or it would sit under the pointer showing nothing until
    // the pointer left and came back.
    if (held && at && isInsideRect(at, held.getBoundingClientRect())) {
      held.dispatchEvent(
        new MouseEvent("mouseenter", {
          bubbles: false,
          clientX: at.x,
          clientY: at.y,
        }),
      );
    }
  }

  return {
    arm({ trigger, card, x, y }) {
      disarm();
      const exit = { x, y };
      run = {
        trigger,
        card,
        exit,
        held: null,
        at: exit,
        heading: heading(latest, exit),
        settling: undefined,
      };
      document.addEventListener("mouseenter", onEnterCapture, true);
    },
    release,
    disarm,
    destroy() {
      disarm();
      document.removeEventListener("pointermove", trackPointer);
    },
  };
}
