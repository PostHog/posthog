import { describe, expect, it, vi } from "vitest";
import {
  COMMENT_ACTION_BUTTON_THEMES,
  commentActionButtonCss,
  commentActionButtonCssVars,
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

describe("selectionCommentAction", () => {
  it("suppresses selection reporting while the user drags, then reports the settled selection", () => {
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
    expect(callbacks.onSelectionSettled).toHaveBeenCalledTimes(1);
    remove();
  });

  it("reports immediately when the selection changes without a drag", () => {
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

  it("cancels the gesture on window blur so a release outside the window can't stick the action hidden", () => {
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
    expect(callbacks.onSelectionSettled).not.toHaveBeenCalled();

    changeSelection();
    expect(callbacks.onGestureCancel).toHaveBeenCalledTimes(1);
    remove();
  });

  it("settles on pointercancel so touch gesture interruptions still show the action", () => {
    const callbacks = { onSelectionSettled: vi.fn() };
    const remove = installSelectionSettleGate(document, callbacks);
    const target = eventTarget();

    press(target);
    target.dispatchEvent(new PointerEvent("pointercancel", { bubbles: true }));
    expect(callbacks.onSelectionSettled).toHaveBeenCalledTimes(1);
    remove();
  });

  it("applies every theme variable the action button styles reference", () => {
    for (const theme of ["light", "dark"] as const) {
      setCommentActionTheme(theme, COMMENT_ACTION_BUTTON_THEMES);
      const css = commentActionButtonCss();
      for (const match of css.matchAll(
        /var\((--ph-comment-action-[a-z-]+)\)/g,
      )) {
        expect(
          document.documentElement.style.getPropertyValue(match[1]),
          `${theme} sets ${match[1]}`,
        ).toBe(COMMENT_ACTION_BUTTON_THEMES[theme][cssVarField(match[1])]);
      }
    }
    document.documentElement.style.cssText = "";
  });

  it("falls back to the light palette for an unknown theme name", () => {
    setCommentActionTheme("solarized", COMMENT_ACTION_BUTTON_THEMES);
    expect(
      document.documentElement.style.getPropertyValue("--ph-comment-action-bg"),
    ).toBe(COMMENT_ACTION_BUTTON_THEMES.light.background);
    document.documentElement.style.cssText = "";
  });

  it("bakes the requested theme into the :root variable declarations", () => {
    expect(commentActionButtonCssVars("dark")).toContain(
      COMMENT_ACTION_BUTTON_THEMES.dark.background,
    );
    expect(commentActionButtonCssVars("light")).toContain(
      COMMENT_ACTION_BUTTON_THEMES.light.background,
    );
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
  };
  return fields[variable];
}
