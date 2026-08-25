import { describe, expect, it } from "vitest";
import { isInteractiveTarget } from "./ReportTriageFocus";

describe("isInteractiveTarget", () => {
  function firstEl(html: string): HTMLElement {
    const container = document.createElement("div");
    container.innerHTML = html;
    return container.firstElementChild as HTMLElement;
  }

  // Guards the triage Enter shortcut: any control the card renders (Next, Exit,
  // a section toggle, a verdict button, the merged-PR link) must own Enter, or
  // Tab-then-Enter exits triage instead of activating the control.
  it.each<[string, boolean]>([
    ["<button>Exit</button>", true],
    ['<a href="https://x">PR</a>', true],
    ["<a>no href</a>", false],
    ['<div role="button">toggle</div>', true],
    ["<div>plain</div>", false],
  ])("classifies %s as interactive=%s", (html, expected) => {
    expect(isInteractiveTarget(firstEl(html))).toBe(expected);
  });

  it("resolves a nested child up to its interactive ancestor", () => {
    const button = firstEl("<button><span>icon</span></button>");
    expect(isInteractiveTarget(button.firstElementChild)).toBe(true);
  });

  it("returns false for null or a non-element target", () => {
    expect(isInteractiveTarget(null)).toBe(false);
    expect(isInteractiveTarget(document)).toBe(false);
  });
});
