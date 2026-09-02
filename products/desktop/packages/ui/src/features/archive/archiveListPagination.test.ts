import type { ArchivedTaskWithRepo } from "@posthog/core/archive/archiveListView";
import { describe, expect, it } from "vitest";
import {
  getVisibleArchivedTasks,
  shouldLoadMoreArchivedTasks,
} from "./archiveListPagination";

function item(
  id: string,
  title: string,
  archivedAt: string,
): ArchivedTaskWithRepo {
  return {
    archived: {
      taskId: id,
      archivedAt,
      folderId: "",
      mode: "cloud",
      worktreeName: null,
      branchName: null,
      checkpointId: null,
    },
    task: {
      id,
      title,
      created_at: archivedAt,
      repository: "posthog/code",
    },
    repoName: "code",
  };
}

const defaultSort = { column: "archived", direction: "desc" } as const;

describe("getVisibleArchivedTasks", () => {
  it("finds matches outside the unfiltered page prefix", () => {
    const items = [
      item("first", "First task", "2026-01-03T00:00:00Z"),
      item("second", "Matching task", "2026-01-02T00:00:00Z"),
    ];

    expect(
      getVisibleArchivedTasks(
        items,
        { searchQuery: "matching", repoFilter: null, sort: defaultSort },
        1,
      ).map((entry) => entry.archived.taskId),
    ).toEqual(["second"]);
  });

  it("sorts the complete archive before limiting rows", () => {
    const items = [
      item("older", "Older task", "2026-01-01T00:00:00Z"),
      item("newer", "Newer task", "2026-01-03T00:00:00Z"),
    ];

    expect(
      getVisibleArchivedTasks(
        items,
        { searchQuery: "", repoFilter: null, sort: defaultSort },
        1,
      ).map((entry) => entry.archived.taskId),
    ).toEqual(["newer"]);
  });
});

describe("shouldLoadMoreArchivedTasks", () => {
  it("loads near the unfiltered boundary", () => {
    expect(shouldLoadMoreArchivedTasks(40, 50, false)).toBe(true);
  });

  it("does not load from the end of filtered results", () => {
    expect(shouldLoadMoreArchivedTasks(0, 1, true)).toBe(false);
  });
});
