import { describe, expect, it } from "vitest";

import {
  formatPlanCapture,
  formatTodoCapture,
  toggleTaskCheckbox,
} from "./markdown";

describe("channel document markdown helpers", () => {
  it.each([
    {
      name: "collapses multi-line selections into one item",
      text: "  fix the retry\n  logic in a follow-up PR  ",
      expected: "- [ ] fix the retry logic in a follow-up PR",
    },
    {
      name: "truncates very long selections with an ellipsis",
      text: "a".repeat(300),
      expected: `- [ ] ${"a".repeat(199)}…`,
    },
  ])("formatTodoCapture $name", ({ text, expected }) => {
    expect(formatTodoCapture(text)).toBe(expected);
  });

  it("formatTodoCapture appends an escaped provenance link", () => {
    expect(
      formatTodoCapture("do the thing", {
        label: "Fix [beta] (v2)",
        url: "posthog-code://task/abc",
      }),
    ).toBe(
      "- [ ] do the thing (from [Fix \\[beta\\] \\(v2\\)](posthog-code://task/abc))",
    );
  });

  it("formatPlanCapture quotes lines and keeps the source on its own line", () => {
    expect(
      formatPlanCapture("first line\n\nsecond line\n", {
        label: "My task",
        url: "posthog-code://task/abc",
      }),
    ).toBe(
      "> first line\n>\n> second line\n> (from [My task](posthog-code://task/abc))",
    );
  });

  const doc = [
    "# Todos",
    "- [ ] first",
    "```",
    "- [ ] not a real checkbox",
    "```",
    "- [x] second",
    "1. [ ] third",
  ].join("\n");

  it.each([
    { index: 0, line: "- [x] first" },
    { index: 1, line: "- [ ] second" },
    { index: 2, line: "1. [x] third" },
  ])(
    "toggleTaskCheckbox flips checkbox $index skipping code fences",
    ({ index, line }) => {
      expect(toggleTaskCheckbox(doc, index)).toContain(line);
    },
  );

  it("toggleTaskCheckbox returns null for an out-of-range index", () => {
    expect(toggleTaskCheckbox(doc, 3)).toBeNull();
    expect(toggleTaskCheckbox(doc, -1)).toBeNull();
  });
});
