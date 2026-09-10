import {
  createSafeTriangleGuard,
  isInSafeTriangle,
  type SafeTriangleGuard,
} from "@posthog/ui/features/canvas/components/safeTriangle";
import { domRect, place } from "@posthog/ui/test/rects";
import { afterEach, describe, expect, it, vi } from "vitest";

/** A card 300 wide and 500 tall, open to the right of a row in a 240px sidebar. */
const CARD = domRect(250, 100, 550, 600);

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
    const flipped = domRect(-400, 100, -100, 600);

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
    place(node, at);
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

  function move(x: number, y: number) {
    document.dispatchEvent(
      new MouseEvent("pointermove", { clientX: x, clientY: y }),
    );
  }

  function scenario(from?: { x: number; y: number }) {
    const guard = createSafeTriangleGuard();
    guards.push(guard);
    const source = element(domRect(0, 100, 240, 128), true);
    const next = element(domRect(0, 128, 240, 156), true);
    const crossed = element(domRect(0, 300, 240, 328), true);
    const card = element(CARD, false);
    if (from) {
      move(from.x, from.y);
    }
    guard.arm({ trigger: source.node, card: card.node, x: 40, y: 128 });
    return { guard, source, next, crossed, card };
  }

  interface Crossing {
    case: string;
    row: "next" | "crossed";
    from?: { x: number; y: number };
    at: { x: number; y: number };
    hovered: boolean;
  }

  it.each<Crossing>([
    {
      case: "crossed well inside the corridor",
      row: "crossed",
      at: { x: 150, y: 320 },
      hovered: false,
    },
    {
      case: "crossed well outside it, nowhere near the card",
      row: "crossed",
      at: { x: 40, y: 320 },
      hovered: true,
    },
    {
      case: "met at the exit point, running at the card",
      row: "next",
      from: { x: 26, y: 122 },
      at: { x: 40, y: 128 },
      hovered: false,
    },
    {
      case: "met at the exit point, stepping down the list",
      row: "next",
      from: { x: 40, y: 114 },
      at: { x: 40, y: 128 },
      hovered: true,
    },
    {
      case: "met at the exit point by a pointer with no history",
      row: "next",
      at: { x: 40, y: 128 },
      hovered: false,
    },
  ])("$case, hover heard: $hovered", ({ row, from, at, hovered }) => {
    const scene = scenario(from);
    const target = row === "next" ? scene.next : scene.crossed;

    enter(target.node, at.x, at.y);

    expect(target.hovers).toHaveBeenCalledTimes(hovered ? 1 : 0);
  });

  it("gives the card to a row a run set out across and stopped on", () => {
    vi.useFakeTimers();
    try {
      const { next } = scenario({ x: 26, y: 122 });

      enter(next.node, 40, 128);
      expect(next.hovers).not.toHaveBeenCalled();
      vi.advanceTimersByTime(200);

      expect(next.hovers).toHaveBeenCalledOnce();
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps running when the pointer is past the row it last crossed", () => {
    vi.useFakeTimers();
    try {
      const { next, crossed } = scenario({ x: 26, y: 122 });

      enter(next.node, 40, 128);
      move(150, 200);
      vi.advanceTimersByTime(200);
      enter(crossed.node, 200, 320);

      expect(next.hovers).not.toHaveBeenCalled();
      expect(crossed.hovers).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
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
