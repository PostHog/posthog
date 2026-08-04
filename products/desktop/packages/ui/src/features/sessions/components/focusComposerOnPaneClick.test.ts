import type { MouseEvent as ReactMouseEvent } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { focusComposerOnPaneClick } from "./focusComposerOnPaneClick";

function clickTarget(target: EventTarget): Pick<ReactMouseEvent, "target"> {
  return { target };
}

afterEach(() => {
  window.getSelection()?.removeAllRanges();
  document.body.replaceChildren();
});

describe("focusComposerOnPaneClick", () => {
  it.each([
    {
      name: "chat content",
      markup: '<p id="target">Chat content</p>',
      expectsFocus: true,
    },
    {
      name: "an interactive element",
      markup: '<button id="target">Open</button>',
      expectsFocus: false,
    },
    {
      name: "content marked as interactive",
      markup: '<span id="target" data-interactive>Open</span>',
      expectsFocus: false,
    },
  ])("focuses for $name only when appropriate", ({ markup, expectsFocus }) => {
    document.body.innerHTML = markup;
    const focusComposer = vi.fn();
    const target = document.getElementById("target") as HTMLElement;

    focusComposerOnPaneClick(clickTarget(target), focusComposer);

    expect(focusComposer).toHaveBeenCalledTimes(expectsFocus ? 1 : 0);
  });

  it("does not focus while selecting chat content", () => {
    document.body.innerHTML = '<p id="target">Chat content</p>';
    const target = document.getElementById("target") as HTMLElement;
    const range = document.createRange();
    range.selectNodeContents(target);
    window.getSelection()?.addRange(range);
    const focusComposer = vi.fn();

    focusComposerOnPaneClick(clickTarget(target), focusComposer);

    expect(focusComposer).not.toHaveBeenCalled();
  });
});
