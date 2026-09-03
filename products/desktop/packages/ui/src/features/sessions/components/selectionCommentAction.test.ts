import { describe, expect, it, vi } from "vitest";
import {
  COMMENT_ACTION_BUTTON_THEMES,
  commentActionAnchorRect,
  commentActionButtonCss,
  computeCommentActionPlacement,
  installSelectionSettleGate,
  type SelectionSettleGateCallbacks,
  setCommentActionTheme,
} from "./selectionCommentAction";

function eventTarget(element?: Element): Element {
  const target = element ?? document.createElement("p");
  if (!target.isConnected) document.body.appendChild(target);
  return target;
}

function press(target: Element): void {
  target.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
}

function release(target: Element): void {
  target.dispatchEvent(new PointerEvent("pointerup", { bubbles: true }));
}

function changeSelection(): void {
  document.dispatchEvent(new Event("selectionchange"));
}

function settleFrames(): Promise<void> {
  return new Promise((resolve) => {
    requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
  });
}

describe("selectionCommentAction", () => {
  it("suppresses selection reporting while the user drags, then reports the settled selection", async () => {
    const callbacks = {
      onGestureStart: vi.fn(),
      onSelectionSettled: vi.fn(),
      onIdleSelectionChange: vi.fn(),
    } satisfies SelectionSettleGateCallbacks;
    const remove = installSelectionSettleGate(document, callbacks);
    const target = eventTarget();

    press(target);
    expect(callbacks.onGestureStart).toHaveBeenCalledTimes(1);

    changeSelection();
    changeSelection();
    expect(callbacks.onIdleSelectionChange).not.toHaveBeenCalled();

    release(target);
    // The browser commits the range after pointerup, so the report waits.
    expect(callbacks.onSelectionSettled).not.toHaveBeenCalled();
    await settleFrames();
    expect(callbacks.onSelectionSettled).toHaveBeenCalledTimes(1);
    remove();
  });

  it("hides on selectstart, for drags whose pointerdown never reached the document", async () => {
    const callbacks = {
      onGestureStart: vi.fn(),
      onIdleSelectionChange: vi.fn(),
      onSelectionSettled: vi.fn(),
    } satisfies SelectionSettleGateCallbacks;
    const remove = installSelectionSettleGate(document, callbacks);
    const target = eventTarget();

    target.dispatchEvent(new Event("selectstart", { bubbles: true }));
    expect(callbacks.onGestureStart).toHaveBeenCalledTimes(1);

    changeSelection();
    expect(callbacks.onIdleSelectionChange).not.toHaveBeenCalled();

    release(target);
    await settleFrames();
    expect(callbacks.onSelectionSettled).toHaveBeenCalledTimes(1);
    remove();
  });

  it("reports immediately when the selection changes without a gesture", () => {
    const callbacks = { onIdleSelectionChange: vi.fn() };
    const remove = installSelectionSettleGate(document, callbacks);

    changeSelection();
    expect(callbacks.onIdleSelectionChange).toHaveBeenCalledTimes(1);
    remove();
  });

  it("ignores presses inside the action UI so pressing the comment button doesn't hide it", () => {
    const callbacks = {
      onGestureStart: vi.fn(),
      onIdleSelectionChange: vi.fn(),
    } satisfies SelectionSettleGateCallbacks;
    const remove = installSelectionSettleGate(document, callbacks);
    const overlay = document.createElement("div");
    overlay.setAttribute("data-selection-comment-overlay", "");
    const innerButton = document.createElement("button");
    overlay.appendChild(innerButton);
    document.body.appendChild(overlay);

    press(innerButton);
    expect(callbacks.onGestureStart).not.toHaveBeenCalled();

    changeSelection();
    expect(callbacks.onIdleSelectionChange).toHaveBeenCalledTimes(1);
    remove();
    overlay.remove();
  });

  it.each(["Shift", "ArrowLeft", "Home", "End", "PageUp", "PageDown"])(
    "ignores the %s selection key while focus is inside the comment UI",
    (key) => {
      const callbacks = {
        onGestureStart: vi.fn(),
        onSelectionSettled: vi.fn(),
      } satisfies SelectionSettleGateCallbacks;
      const remove = installSelectionSettleGate(document, callbacks);
      const overlay = document.createElement("div");
      overlay.setAttribute("data-selection-comment-overlay", "");
      const textarea = document.createElement("textarea");
      overlay.appendChild(textarea);
      document.body.appendChild(overlay);

      textarea.dispatchEvent(
        new KeyboardEvent("keydown", { key, bubbles: true }),
      );
      textarea.dispatchEvent(
        new KeyboardEvent("keyup", { key, bubbles: true }),
      );
      expect(callbacks.onGestureStart).not.toHaveBeenCalled();
      expect(callbacks.onSelectionSettled).not.toHaveBeenCalled();

      remove();
      overlay.remove();
    },
  );

  it("ignores secondary buttons, which open menus instead of selecting", () => {
    const callbacks = { onGestureStart: vi.fn() };
    const remove = installSelectionSettleGate(document, callbacks);
    const target = eventTarget();

    target.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true, button: 2 }),
    );
    expect(callbacks.onGestureStart).not.toHaveBeenCalled();
    remove();
  });

  it("cancels the gesture on window blur so a release outside the window can't stick the action hidden", async () => {
    const callbacks = {
      onGestureCancel: vi.fn(),
      onSelectionSettled: vi.fn(),
    } satisfies SelectionSettleGateCallbacks;
    const remove = installSelectionSettleGate(document, callbacks);
    const target = eventTarget();

    press(target);
    window.dispatchEvent(new Event("blur"));
    expect(callbacks.onGestureCancel).toHaveBeenCalledTimes(1);

    release(target);
    await settleFrames();
    expect(callbacks.onSelectionSettled).not.toHaveBeenCalled();
    remove();
  });

  it("cancels on pointercancel, which trackpads fire mid-drag", async () => {
    const callbacks = {
      onSelectionSettled: vi.fn(),
      onGestureCancel: vi.fn(),
    } satisfies SelectionSettleGateCallbacks;
    const remove = installSelectionSettleGate(document, callbacks);
    const target = eventTarget();

    press(target);
    target.dispatchEvent(new PointerEvent("pointercancel", { bubbles: true }));
    await settleFrames();
    expect(callbacks.onGestureCancel).toHaveBeenCalledTimes(1);
    expect(callbacks.onSelectionSettled).not.toHaveBeenCalled();
    remove();
  });

  it("holds keyboard selections until the key is released", async () => {
    const callbacks = {
      onGestureStart: vi.fn(),
      onSelectionSettled: vi.fn(),
      onIdleSelectionChange: vi.fn(),
    } satisfies SelectionSettleGateCallbacks;
    const remove = installSelectionSettleGate(document, callbacks);

    for (let repeat = 0; repeat < 3; repeat++) {
      document.dispatchEvent(
        new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }),
      );
    }
    expect(callbacks.onGestureStart).toHaveBeenCalledTimes(1);
    changeSelection();
    expect(callbacks.onIdleSelectionChange).not.toHaveBeenCalled();

    document.dispatchEvent(
      new KeyboardEvent("keyup", { key: "ArrowRight", bubbles: true }),
    );
    await settleFrames();
    expect(callbacks.onSelectionSettled).toHaveBeenCalledTimes(1);
    remove();
  });

  it("still treats Shift outside the comment UI as a selection gesture", async () => {
    const callbacks = {
      onGestureStart: vi.fn(),
      onSelectionSettled: vi.fn(),
    } satisfies SelectionSettleGateCallbacks;
    const remove = installSelectionSettleGate(document, callbacks);
    const target = eventTarget();

    target.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Shift", bubbles: true }),
    );
    expect(callbacks.onGestureStart).toHaveBeenCalledTimes(1);

    target.dispatchEvent(
      new KeyboardEvent("keyup", { key: "Shift", bubbles: true }),
    );
    await settleFrames();
    expect(callbacks.onSelectionSettled).toHaveBeenCalledTimes(1);
    remove();
  });

  it("distinguishes typing from select-all and settles after the modifier is released", async () => {
    const callbacks = {
      onGestureStart: vi.fn(),
      onSelectionSettled: vi.fn(),
    } satisfies SelectionSettleGateCallbacks;
    const remove = installSelectionSettleGate(document, callbacks);

    document.dispatchEvent(
      new KeyboardEvent("keydown", { key: "a", bubbles: true }),
    );
    expect(callbacks.onGestureStart).not.toHaveBeenCalled();

    document.dispatchEvent(
      new KeyboardEvent("keydown", { key: "a", metaKey: true, bubbles: true }),
    );
    expect(callbacks.onGestureStart).toHaveBeenCalledTimes(1);

    document.dispatchEvent(
      new KeyboardEvent("keyup", { key: "a", metaKey: false, bubbles: true }),
    );
    await settleFrames();
    expect(callbacks.onSelectionSettled).toHaveBeenCalledTimes(1);
    remove();
  });

  it("applies every theme variable the action button styles reference", () => {
    const target = document.createElement("button");
    for (const theme of ["light", "dark"] as const) {
      setCommentActionTheme(theme, COMMENT_ACTION_BUTTON_THEMES, target);
      const css = commentActionButtonCss();
      for (const match of css.matchAll(
        /var\((--ph-comment-action-[a-z-]+)\)/g,
      )) {
        expect(
          target.style.getPropertyValue(match[1]),
          `${theme} sets ${match[1]}`,
        ).toBe(COMMENT_ACTION_BUTTON_THEMES[theme][cssVarField(match[1])]);
      }
    }
  });

  it("falls back to the light palette for an unknown theme name", () => {
    const target = document.createElement("button");
    setCommentActionTheme("solarized", COMMENT_ACTION_BUTTON_THEMES, target);
    expect(target.style.getPropertyValue("--ph-comment-action-bg")).toBe(
      COMMENT_ACTION_BUTTON_THEMES.light.background,
    );
  });
});

describe("commentActionAnchorRect", () => {
  const box = (left: number, top: number, right: number, bottom: number) => ({
    left,
    top,
    right,
    bottom,
    width: right - left,
    height: bottom - top,
  });
  const fallback = box(0, 0, 10, 10);

  it("ignores the wrapper box a multi-line selection reports, anchoring to the last line", () => {
    const firstLine = box(600, 340, 1213, 364);
    const lastLine = box(628, 447, 866, 470);
    // A blockquote/paragraph wrapper encloses every line box and, in DOM order,
    // can come last — the case that threw the action to the far right.
    const wrapper = box(578, 310, 1274, 596);

    expect(
      commentActionAnchorRect([firstLine, lastLine, wrapper], fallback),
    ).toBe(lastLine);
  });

  it("takes the right-most box when the selection ends on a line split across elements", () => {
    const plain = box(100, 40, 180, 60);
    const bolded = box(180, 40, 240, 60);

    expect(commentActionAnchorRect([bolded, plain], fallback)).toBe(bolded);
  });

  it("falls back when the range reports no boxes at all", () => {
    expect(commentActionAnchorRect([], fallback)).toBe(fallback);
    expect(commentActionAnchorRect([box(5, 5, 5, 5)], fallback)).toBe(fallback);
  });
});

describe("computeCommentActionPlacement", () => {
  const bounds = { width: 1000, height: 700 };
  const action = { width: 120, height: 30 };

  it("sits right of the selection end, vertically centered on the end line", () => {
    expect(
      computeCommentActionPlacement(
        { top: 100, right: 400, bottom: 120 },
        bounds,
        action,
      ),
    ).toEqual({ top: 95, left: 408 });
  });

  it("drops below the end line when the right edge has no room, right-aligned to the caret", () => {
    expect(
      computeCommentActionPlacement(
        { top: 100, right: 950, bottom: 120 },
        bounds,
        action,
      ),
    ).toEqual({ top: 126, left: 830 });
  });

  it("flips above the end line when below would leave the viewport", () => {
    expect(
      computeCommentActionPlacement(
        { top: 100, right: 950, bottom: 120 },
        { width: 1000, height: 140 },
        action,
      ),
    ).toEqual({ top: 64, left: 830 });
  });

  it("places the expanded composer below the selection", () => {
    expect(
      computeCommentActionPlacement(
        { top: 100, right: 400, bottom: 120 },
        bounds,
        { width: 420, height: 180 },
        "below",
      ),
    ).toEqual({ top: 126, left: 408 });
  });

  it("clamps to the viewport margins for selections hugging the edges", () => {
    expect(
      computeCommentActionPlacement(
        { top: 4, right: 2, bottom: 12 },
        bounds,
        action,
      ),
    ).toEqual({ top: 8, left: 10 });
  });
});

function cssVarField(
  variable: string,
): keyof (typeof COMMENT_ACTION_BUTTON_THEMES)["light"] {
  const fields: Record<
    string,
    keyof (typeof COMMENT_ACTION_BUTTON_THEMES)["light"]
  > = {
    "--ph-comment-action-bg": "background",
    "--ph-comment-action-fg": "color",
    "--ph-comment-action-border": "border",
    "--ph-comment-action-hover": "hoverBackground",
    "--ph-comment-action-shadow": "shadow",
  };
  return fields[variable];
}
