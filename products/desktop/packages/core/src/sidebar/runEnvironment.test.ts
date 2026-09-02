import { describe, expect, it } from "vitest";
import { mostRecentRunEnvironment } from "./runEnvironment";
import type { TaskData } from "./sidebarData.types";

const task = (overrides: Partial<TaskData>): TaskData => ({
  id: "t",
  title: "t",
  createdAt: 0,
  lastActivityAt: 0,
  isGenerating: false,
  isUnread: false,
  isPinned: false,
  needsPermission: false,
  repository: null,
  isSuspended: false,
  folderPath: null,
  cloudPrUrl: null,
  branchName: null,
  linkedBranch: null,
  ...overrides,
});

describe("mostRecentRunEnvironment", () => {
  it("returns undefined when no task has run", () => {
    expect(mostRecentRunEnvironment([])).toBeUndefined();
    expect(
      mostRecentRunEnvironment([task({ taskRunEnvironment: undefined })]),
    ).toBeUndefined();
  });

  it("returns the environment of the most recently active run", () => {
    expect(
      mostRecentRunEnvironment([
        task({ id: "old", lastActivityAt: 1, taskRunEnvironment: "cloud" }),
        task({ id: "new", lastActivityAt: 2, taskRunEnvironment: "local" }),
      ]),
    ).toBe("local");
  });

  it("picks the most recent regardless of array order", () => {
    // Same tasks as above, most-recent listed first: position must not matter.
    expect(
      mostRecentRunEnvironment([
        task({ id: "new", lastActivityAt: 2, taskRunEnvironment: "local" }),
        task({ id: "old", lastActivityAt: 1, taskRunEnvironment: "cloud" }),
      ]),
    ).toBe("local");
  });

  it("ignores tasks without a recorded environment (drafts) when picking the most recent", () => {
    expect(
      mostRecentRunEnvironment([
        task({ id: "ran", lastActivityAt: 1, taskRunEnvironment: "cloud" }),
        task({ id: "draft", lastActivityAt: 5, taskRunEnvironment: undefined }),
      ]),
    ).toBe("cloud");
  });
});
