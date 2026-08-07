import { describe, expect, it } from "vitest";
import {
  BRANCH_PREFIX,
  slugifyWorktreeName,
  worktreeNameFromBranch,
} from "./git-naming";

describe("slugifyWorktreeName", () => {
  it.each([
    [
      "already-clean input passes through unchanged",
      "fix-login-bug",
      "fix-login-bug",
    ],
    ["lowercases uppercase letters", "Fix-Login-Bug", "fix-login-bug"],
    ["replaces slashes with hyphens", "feature/add-login", "feature-add-login"],
    ["replaces spaces with hyphens", "fix login bug", "fix-login-bug"],
    [
      "collapses a run of special characters into a single hyphen",
      "fix!!login??bug",
      "fix-login-bug",
    ],
    [
      "collapses adjacent separator runs instead of stacking hyphens",
      "fix // login  bug",
      "fix-login-bug",
    ],
    ["trims a leading separator run", "--fix-login", "fix-login"],
    ["trims a trailing separator run", "fix-login--", "fix-login"],
    ["keeps digits", "fix-login-v2", "fix-login-v2"],
    ["returns null for an empty string", "", null],
    ["returns null for whitespace-only input", "   ", null],
    ["returns null for symbols-only input", "!!!///???", null],
  ])("%s", (_name, input, expected) => {
    expect(slugifyWorktreeName(input)).toBe(expected);
  });

  it("caps the result at 60 characters", () => {
    const input = "a".repeat(80);
    const result = slugifyWorktreeName(input);
    expect(result).toHaveLength(60);
    expect(result).toBe("a".repeat(60));
  });

  it("does not leave a trailing hyphen after truncating at the cap", () => {
    // A hyphen landing exactly at the 60-char cut point must not survive as a
    // trailing separator once the rest of the string is truncated away.
    const input = `${"a".repeat(59)}-bbbb`;
    const result = slugifyWorktreeName(input);
    expect(result).not.toBeNull();
    expect(result?.length).toBeLessThanOrEqual(60);
    expect(result?.endsWith("-")).toBe(false);
  });
});

describe("worktreeNameFromBranch", () => {
  it.each([
    [
      "strips the posthog-code/ prefix before slugifying",
      `${BRANCH_PREFIX}fix-login-bug`,
      "fix-login-bug",
    ],
    [
      "strips the prefix and converts remaining slashes to hyphens",
      `${BRANCH_PREFIX}feature/add-login`,
      "feature-add-login",
    ],
    [
      "converts slashes to hyphens with no prefix present",
      "feature/add-login",
      "feature-add-login",
    ],
    [
      "leaves an already-clean branch name unchanged",
      "fix-login-bug",
      "fix-login-bug",
    ],
    [
      "returns null when only the prefix remains after stripping",
      BRANCH_PREFIX,
      null,
    ],
    ["returns null for an empty branch name", "", null],
  ])("%s", (_name, branch, expected) => {
    expect(worktreeNameFromBranch(branch)).toBe(expected);
  });

  it("does not strip a prefix that only partially matches", () => {
    // A branch that merely starts with the same characters as BRANCH_PREFIX
    // but isn't actually namespaced under it must not be mistaken for one.
    const almostPrefix = `${BRANCH_PREFIX.slice(0, -1)}x/feature`;
    expect(worktreeNameFromBranch(almostPrefix)).toBe(
      slugifyWorktreeName(almostPrefix),
    );
  });
});
