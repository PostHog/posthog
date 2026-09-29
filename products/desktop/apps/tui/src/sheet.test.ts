import { stripTerminalSequences } from "@earendil-works/pi-tui";
import { describe, expect, it } from "vitest";
import { moveCursor, renderSheet, type Sheet, sheetKey } from "./sheet";

const plain = (lines: string[]): string[] =>
  lines.map((line) => stripTerminalSequences(line).trimEnd());

const models: Sheet = {
  title: "Select model",
  description: "Applies to this chat.",
  items: [
    { label: "Default", detail: "GPT 5.6 Terra" },
    { label: "Opus 5.5", detail: "For complex work", current: true },
    {
      label: "Sonnet 5.5",
      detail: "Efficient",
      disabled: "PostHog Desktop only",
    },
  ],
  footer: "Enter to select · Esc to cancel",
};

describe("renderSheet", () => {
  it("draws a titled, numbered list with the cursor, the current pick and a footer", () => {
    expect(plain(renderSheet(models, 1, 60))).toEqual([
      "─".repeat(60),
      "",
      " Select model",
      " Applies to this chat.",
      "",
      "   1. Default     GPT 5.6 Terra",
      " ❯ 2. Opus 5.5 ✔  For complex work",
      "   3. Sonnet 5.5  Efficient (PostHog Desktop only)",
      "",
      " Enter to select · Esc to cancel",
    ]);
  });

  it("shows a window of long lists around the cursor with a count of the rest", () => {
    const long: Sheet = {
      title: "Pick",
      items: Array.from({ length: 12 }, (_, i) => ({ label: `Item ${i + 1}` })),
    };
    const lines = plain(renderSheet(long, 11, 40, 5));

    expect(lines.filter((line) => /\d+\. Item/.test(line))).toHaveLength(5);
    expect(lines).toContain(" ❯ 12. Item 12");
    expect(lines).toContain("     … +7 more");
  });
});

describe("moveCursor", () => {
  it.each([
    [0, 1, 1],
    [2, 1, 2],
    [0, -1, 0],
  ])("from %d by %d lands on %d", (from, step, to) => {
    expect(moveCursor(models, from, step as 1 | -1)).toBe(to);
  });
});

describe("sheetKey", () => {
  it.each([
    ["\x1b[A", { kind: "up" }],
    ["\x1b[B", { kind: "down" }],
    ["\r", { kind: "choose" }],
    ["\x1b", { kind: "dismiss" }],
    ["3", { kind: "number", index: 2 }],
    ["a", null],
  ])("maps %j", (sequence, expected) => {
    expect(sheetKey(sequence)).toEqual(expected);
  });
});
