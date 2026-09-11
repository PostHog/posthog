import { describe, expect, it } from "vitest";
import {
  isTextEntryTarget,
  resolveReportCardClickIntent,
} from "./reportSelection";

const plain = { shiftKey: false, metaKey: false, ctrlKey: false };

describe("report card selection", () => {
  it.each([
    [
      "a plain click with nothing selected opens the report",
      plain,
      false,
      "open",
    ],
    ["a plain click in selection mode toggles instead", plain, true, "toggle"],
    [
      "Cmd-click toggles from an empty selection",
      { ...plain, metaKey: true },
      false,
      "toggle",
    ],
    [
      "Ctrl-click toggles from an empty selection",
      { ...plain, ctrlKey: true },
      false,
      "toggle",
    ],
    ["Shift-click ranges", { ...plain, shiftKey: true }, false, "range"],
    [
      "Shift wins over Cmd",
      { shiftKey: true, metaKey: true, ctrlKey: false },
      true,
      "range",
    ],
  ])("%s", (_label, modifiers, hasSelection, expected) => {
    expect(resolveReportCardClickIntent(modifiers, hasSelection)).toBe(
      expected,
    );
  });

  it.each([
    ["a text input", "input", { type: "text" }, true],
    ["a search input", "input", { type: "search" }, true],
    ["a textarea", "textarea", {}, true],
    [
      "a checkbox, which Escape has no use for",
      "input",
      { type: "checkbox" },
      false,
    ],
    [
      "a button, which Escape has no use for",
      "input",
      { type: "button" },
      false,
    ],
    ["a card", "div", {}, false],
  ])("treats %s as a text-entry target: %s", (_label, tag, attrs, expected) => {
    const element = document.createElement(tag);
    Object.assign(element, attrs);

    expect(isTextEntryTarget(element)).toBe(expected);
  });

  it("treats a non-element target as no target at all", () => {
    expect(isTextEntryTarget(null)).toBe(false);
  });
});
