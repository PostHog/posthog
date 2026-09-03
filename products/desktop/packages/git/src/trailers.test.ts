import { describe, expect, it } from "vitest";
import { stripClaudeAttribution } from "./trailers";

describe("stripClaudeAttribution", () => {
  it.each([
    {
      name: "removes the Claude co-author trailer",
      input: "fix: thing\n\nCo-Authored-By: Claude <noreply@anthropic.com>",
      expected: "fix: thing",
    },
    {
      name: "removes the Generated with Claude Code line",
      input:
        "fix: thing\n\n🤖 Generated with [Claude Code](https://claude.com/claude-code)",
      expected: "fix: thing",
    },
    {
      name: "removes both attribution lines together",
      input:
        "fix: thing\n\nReal detail.\n\n🤖 Generated with [Claude Code](https://claude.com/claude-code)\n\nCo-Authored-By: Claude <noreply@anthropic.com>",
      expected: "fix: thing\n\nReal detail.",
    },
    {
      name: "matches the trailer case-insensitively",
      input: "fix\n\nco-authored-by: Claude <noreply@anthropic.com>",
      expected: "fix",
    },
    {
      name: "keeps a non-Anthropic co-author",
      input: "fix\n\nCo-Authored-By: Someone <someone@example.com>",
      expected: "fix\n\nCo-Authored-By: Someone <someone@example.com>",
    },
    {
      name: "leaves a clean message untouched",
      input: "fix: thing\n\nReal detail.",
      expected: "fix: thing\n\nReal detail.",
    },
    {
      name: "returns an empty string for undefined",
      input: undefined,
      expected: "",
    },
  ])("$name", ({ input, expected }) => {
    expect(stripClaudeAttribution(input)).toBe(expected);
  });
});
