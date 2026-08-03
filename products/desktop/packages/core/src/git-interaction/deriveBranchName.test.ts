import { describe, expect, it } from "vitest";
import { deriveBranchName } from "./branchName";

describe("deriveBranchName", () => {
  it("converts a simple title to a branch name", () => {
    expect(deriveBranchName("Fix authentication login bug", "abc123")).toBe(
      "posthog-code/fix-authentication-login-bug",
    );
  });

  it("handles special characters", () => {
    expect(deriveBranchName("PostHog issue #1234", "abc123")).toBe(
      "posthog-code/posthog-issue-1234",
    );
  });

  it("collapses consecutive dashes", () => {
    expect(deriveBranchName("Fix  the   bug", "abc123")).toBe(
      "posthog-code/fix-the-bug",
    );
  });

  it("strips leading and trailing dashes", () => {
    expect(deriveBranchName("  Fix bug  ", "abc123")).toBe(
      "posthog-code/fix-bug",
    );
  });

  it("truncates long titles", () => {
    const longTitle =
      "This is a very long task title that should be truncated to a reasonable length for git";
    const result = deriveBranchName(longTitle, "abc123");
    expect(result.length).toBeLessThanOrEqual(73); // 60 slug + "posthog-code/" prefix
    expect(result.startsWith("posthog-code/")).toBe(true);
    expect(result.endsWith("-")).toBe(false);
  });

  it("falls back to task ID when title is empty", () => {
    expect(deriveBranchName("", "abc123")).toBe("posthog-code/task-abc123");
  });

  it("falls back to task ID when title is only whitespace", () => {
    expect(deriveBranchName("   ", "abc123")).toBe("posthog-code/task-abc123");
  });

  it("falls back to task ID when title is only special characters", () => {
    expect(deriveBranchName("!@#$%", "abc123")).toBe(
      "posthog-code/task-abc123",
    );
  });
});
