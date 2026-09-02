import { ANALYTICS_EVENTS } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import {
  buildBranchMismatchAnalyticsEvent,
  buildCheckoutBranchRequest,
  decideBeforeSubmit,
  resolveSwitchErrorMessage,
} from "./branchMismatchDialog";

const context = {
  taskId: "task-1",
  linkedBranch: "feat/foo",
  currentBranch: "main",
  hasUncommittedChanges: true,
};

describe("decideBeforeSubmit", () => {
  it("allows submit when not warning", () => {
    expect(decideBeforeSubmit(false)).toBe(true);
  });

  it("blocks submit when warning", () => {
    expect(decideBeforeSubmit(true)).toBe(false);
  });
});

describe("buildBranchMismatchAnalyticsEvent", () => {
  it("builds the warning-shown event", () => {
    expect(buildBranchMismatchAnalyticsEvent("shown", context)).toEqual({
      event: ANALYTICS_EVENTS.BRANCH_MISMATCH_WARNING_SHOWN,
      properties: {
        task_id: "task-1",
        linked_branch: "feat/foo",
        current_branch: "main",
        has_uncommitted_changes: true,
      },
    });
  });

  it("builds the action event", () => {
    expect(buildBranchMismatchAnalyticsEvent("switch", context)).toEqual({
      event: ANALYTICS_EVENTS.BRANCH_MISMATCH_ACTION,
      properties: {
        task_id: "task-1",
        action: "switch",
        linked_branch: "feat/foo",
        current_branch: "main",
      },
    });
  });

  it("returns null without both branches", () => {
    expect(
      buildBranchMismatchAnalyticsEvent("cancel", {
        ...context,
        linkedBranch: null,
      }),
    ).toBeNull();
  });
});

describe("buildCheckoutBranchRequest", () => {
  it("builds the request", () => {
    expect(buildCheckoutBranchRequest("/repo", "feat/foo")).toEqual({
      directoryPath: "/repo",
      branchName: "feat/foo",
    });
  });

  it("returns null without repo path", () => {
    expect(buildCheckoutBranchRequest(null, "feat/foo")).toBeNull();
  });

  it("returns null without linked branch", () => {
    expect(buildCheckoutBranchRequest("/repo", null)).toBeNull();
  });
});

describe("resolveSwitchErrorMessage", () => {
  it("uses error message", () => {
    expect(resolveSwitchErrorMessage(new Error("dirty worktree"))).toBe(
      "dirty worktree",
    );
  });

  it("falls back for non-errors", () => {
    expect(resolveSwitchErrorMessage("oops")).toBe("Failed to switch branch");
  });
});
