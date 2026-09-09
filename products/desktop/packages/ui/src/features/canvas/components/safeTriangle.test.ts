import {
  createSafeTriangleGuard,
  isInSafeTriangle,
  type SafeTriangleGuard,
} from "@posthog/ui/features/canvas/components/safeTriangle";
import { afterEach, describe, expect, it, vi } from "vitest";

function rect(
  left: number,
  top: number,
  right: number,
  bottom: number,
): DOMRect {
  return {
    left,
    top,
    right,
    bottom,
    x: left,
    y: top,
    width: right - left,
    height: bottom - top,
    toJSON: () => ({}),
  };
}

/** A card 300 wide and 500 tall, open to the right of a row in a 240px sidebar. */
const CARD = rect(250, 100, 550, 600);

describe("isInSafeTriangle", () => {
  /** Where the pointer left the row: its bottom edge, under the status dot. */
  const exit = { x: 40, y: 110 };

  it.each([
    ["just past the exit point", { x: 60, y: 112 }, true],
    ["low down, but already at the card's edge", { x: 249, y: 560 }, true],
    ["a steep diagonal that still arrives", { x: 150, y: 330 }, true],
    ["low down beside the exit point", { x: 60, y: 400 }, false],
    ["behind the exit point", { x: 20, y: 110 }, false],
    ["past the card's far edge", { x: 700, y: 300 }, false],
    ["above the card entirely", { x: 200, y: 20 }, false],
  ])("%s is inside: %o -> %s", (_case, point, expected) => {
    expect(isInSafeTriangle(point, exit, CARD)).toBe(expected);
  });

  it("aims at the card's right edge when the card sits to the left", () => {
    // A card a screen edge flipped. Fanning out rightwards anyway would guard
    // empty screen and leave the run over the rows unprotected.
    const flipped = rect(-400, 100, -100, 600);

    expect(isInSafeTriangle({ x: 20, y: 112 }, exit, flipped)).toBe(true);
    expect(isInSafeTriangle({ x: 60, y: 112 }, exit, flipped)).toBe(false);
  });
});

describe("createSafeTriangleGuard", () => {
  const guards: SafeTriangleGuard[] = [];

  afterEach(() => {
    for (const guard of guards.splice(0)) {
      guard.disarm();
    }
    document.body.replaceChildren();
  });

  /** An element at a fixed rect, counting the hovers Base UI would act on. */
  function element(at: DOMRect, isRow: boolean) {
    const node = document.createElement("div");
    if (isRow) {
      node.setAttribute("data-preview-card-trigger", "");
    }
    node.getBoundingClientRect = () => at;
    const hovers = vi.fn();
    node.addEventListener("mouseenter", hovers);
    document.body.append(node);
    return { node, hovers };
  }

  function enter(node: Element, x: number, y: number) {
    node.dispatchEvent(
      new MouseEvent("mouseenter", { bubbles: false, clientX: x, clientY: y }),
    );
  }

  /** A card open on the row at the top of the list, just left of the row below. */
  function scenario() {
    const guard = createSafeTriangleGuard();
    guards.push(guard);
    const source = element(rect(0, 100, 240, 128), true);
    const crossed = element(rect(0, 300, 240, 328), true);
    const card = element(CARD, false);
    guard.arm({ trigger: source.node, card: card.node, x: 40, y: 128 });
    return { guard, source, crossed, card };
  }

  it("holds back a row crossed on the way to the card", () => {
    const { crossed } = scenario();

    enter(crossed.node, 150, 320);

    expect(crossed.hovers).not.toHaveBeenCalled();
  });

  it("lets a row outside the corridor take the card", () => {
    const { crossed } = scenario();

    // Straight down the list, nowhere near the card.
    enter(crossed.node, 40, 320);

    expect(crossed.hovers).toHaveBeenCalledOnce();
  });

  it("stops guarding once a row outside the corridor has taken over", () => {
    const { crossed, source } = scenario();

    enter(crossed.node, 40, 320);
    enter(source.node, 40, 110);

    expect(source.hovers).toHaveBeenCalledOnce();
  });

  it("hands the held hover back when the card goes while the pointer rests", () => {
    const { guard, crossed } = scenario();

    enter(crossed.node, 150, 320);
    guard.release();

    expect(crossed.hovers).toHaveBeenCalledOnce();
  });

  it("hands nothing back once the pointer has reached the card", () => {
    const { guard, crossed, card } = scenario();

    enter(crossed.node, 150, 320);
    enter(card.node, 300, 400);
    guard.release();

    expect(crossed.hovers).not.toHaveBeenCalled();
  });

  it("stops listening once disarmed", () => {
    const { guard, crossed } = scenario();

    guard.disarm();
    enter(crossed.node, 150, 320);

    expect(crossed.hovers).toHaveBeenCalledOnce();
  });
});
