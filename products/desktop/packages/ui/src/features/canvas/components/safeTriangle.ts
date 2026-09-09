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
 * Half the height of the sliver the corridor starts as, at the point the
 * pointer left the row. The corridor is a triangle in spirit and a very thin
 * quadrilateral in fact, which is what keeps the maths to one shape.
 */
const EXIT_HALF_HEIGHT = 2;

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
 * Is the pointer still on its way from `exit` to `card`? The corridor is a
 * sliver at the exit point that fans out to the whole of the card's near edge,
 * so a card five hundred pixels tall can be reached from a row twenty-eight
 * pixels tall at any angle that actually arrives.
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
    { x: exit.x, y: exit.y + EXIT_HALF_HEIGHT },
    { x: exit.x, y: exit.y - EXIT_HALF_HEIGHT },
    { x: nearEdgeX, y: card.top },
    { x: nearEdgeX, y: card.bottom },
  ]);
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
}

export function createSafeTriangleGuard(): SafeTriangleGuard {
  interface Run {
    trigger: Element;
    card: Element;
    exit: Point;
    /** The row whose `mouseenter` was held back, and where the pointer was. */
    held: Element | null;
    at: Point;
  }
  let run: Run | null = null;

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
    if (!isInSafeTriangle(at, run.exit, run.card.getBoundingClientRect())) {
      // Off the corridor, so the pointer wants this row and not the card.
      disarm();
      return;
    }
    run.held = row;
    run.at = at;
    event.stopPropagation();
  }

  /** Only while armed, and only to know where a held row was last pointed at. */
  function onMove(event: Event): void {
    if (!run) {
      return;
    }
    const { clientX, clientY } = event as MouseEvent;
    run.at = { x: clientX, y: clientY };
  }

  function detach(): void {
    document.removeEventListener("mouseenter", onEnterCapture, true);
    document.removeEventListener("pointermove", onMove);
  }

  function disarm(): void {
    if (!run) {
      return;
    }
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
      run = { trigger, card, exit: { x, y }, held: null, at: { x, y } };
      document.addEventListener("mouseenter", onEnterCapture, true);
      document.addEventListener("pointermove", onMove);
    },
    release,
    disarm,
  };
}
