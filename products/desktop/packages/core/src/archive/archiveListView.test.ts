import type { ArchivedTask } from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import { describe, expect, it } from "vitest";
import {
  type ArchivedTaskWithDetails,
  deriveUniqueRepos,
  filterAndSortArchivedTasks,
  getRepoName,
  mergeArchivedWithTasks,
  withRepoNames,
} from "./archiveListView";

function makeArchived(taskId: string, archivedAt: string): ArchivedTask {
  return {
    taskId,
    archivedAt,
    folderId: "",
    mode: "worktree",
    worktreeName: null,
    branchName: null,
    checkpointId: null,
  };
}

function makeTask(id: string, partial: Partial<Task> = {}): Task {
  return {
    id,
    title: id,
    created_at: "2024-01-01T00:00:00.000Z",
    repository: null,
    ...partial,
  } as Task;
}

describe("getRepoName", () => {
  it("returns the last path segment of an org/repo string", () => {
    expect(getRepoName("posthog/posthog-js")).toBe("posthog-js");
  });

  it("returns an em dash for nullish input", () => {
    expect(getRepoName(null)).toBe("—");
  });
});

describe("deriveUniqueRepos", () => {
  it("returns sorted unique repo names excluding the em-dash placeholder", () => {
    const items = withRepoNames([
      {
        archived: makeArchived("a", "2024-01-02T00:00:00.000Z"),
        task: makeTask("a", { repository: "o/zed" }),
      },
      {
        archived: makeArchived("b", "2024-01-03T00:00:00.000Z"),
        task: makeTask("b", { repository: "o/alpha" }),
      },
      { archived: makeArchived("c", "2024-01-04T00:00:00.000Z"), task: null },
    ]);
    expect(deriveUniqueRepos(items)).toEqual(["alpha", "zed"]);
  });
});

describe("mergeArchivedWithTasks", () => {
  it("resolves details fetched directly for an archived task", () => {
    const archived = makeArchived("older-task", "2024-01-02T00:00:00.000Z");
    const task = makeTask("older-task", { title: "Recover me" });

    expect(mergeArchivedWithTasks([archived], [task])).toEqual([
      { archived, task },
    ]);
  });

  it.each([
    {
      name: "creation date",
      patch: { taskCreatedAt: undefined },
      expected: {
        title: "Recovered title",
        created_at: null,
        repository: "posthog/code",
      },
    },
    {
      name: "title",
      patch: { title: undefined },
      expected: {
        title: "Unknown task (older-ta)",
        created_at: "2024-01-01T00:00:00.000Z",
        repository: "posthog/code",
      },
    },
    {
      name: "repository",
      patch: { repository: undefined },
      expected: {
        title: "Recovered title",
        created_at: "2024-01-01T00:00:00.000Z",
        repository: null,
      },
    },
  ])(
    "preserves other archived metadata when $name is missing",
    ({ patch, expected }) => {
      const archived = {
        ...makeArchived("older-task", "2024-01-02T00:00:00.000Z"),
        title: "Recovered title",
        taskCreatedAt: "2024-01-01T00:00:00.000Z",
        repository: "posthog/code",
        ...patch,
      };

      expect(mergeArchivedWithTasks([archived], [])[0].task).toEqual({
        id: "older-task",
        ...expected,
      });
    },
  );
});

describe("filterAndSortArchivedTasks", () => {
  const items: ArchivedTaskWithDetails[] = [
    {
      archived: makeArchived("a", "2024-01-02T00:00:00.000Z"),
      task: makeTask("a", { title: "Apple", repository: "o/one" }),
    },
    {
      archived: makeArchived("b", "2024-01-04T00:00:00.000Z"),
      task: makeTask("b", { title: "Banana", repository: "o/two" }),
    },
  ];

  it("filters by search query against task title", () => {
    const result = filterAndSortArchivedTasks(withRepoNames(items), {
      searchQuery: "ban",
      repoFilter: null,
      sort: { column: "archived", direction: "desc" },
    });
    expect(result.map((i) => i.archived.taskId)).toEqual(["b"]);
  });

  it("filters by task id when the original title is unavailable", () => {
    const result = filterAndSortArchivedTasks(withRepoNames(items), {
      searchQuery: "b",
      repoFilter: null,
      sort: { column: "archived", direction: "desc" },
    });
    expect(result.map((i) => i.archived.taskId)).toEqual(["b"]);
  });

  it("filters by repo name", () => {
    const result = filterAndSortArchivedTasks(withRepoNames(items), {
      searchQuery: "",
      repoFilter: "one",
      sort: { column: "archived", direction: "desc" },
    });
    expect(result.map((i) => i.archived.taskId)).toEqual(["a"]);
  });

  it("does not include repository names in the title and task ID search", () => {
    const result = filterAndSortArchivedTasks(withRepoNames(items), {
      searchQuery: "two",
      repoFilter: null,
      sort: { column: "archived", direction: "desc" },
    });
    expect(result).toEqual([]);
  });

  it("sorts by archivedAt descending", () => {
    const result = filterAndSortArchivedTasks(withRepoNames(items), {
      searchQuery: "",
      repoFilter: null,
      sort: { column: "archived", direction: "desc" },
    });
    expect(result.map((i) => i.archived.taskId)).toEqual(["b", "a"]);
  });

  it("sorts by archivedAt ascending", () => {
    const result = filterAndSortArchivedTasks(withRepoNames(items), {
      searchQuery: "",
      repoFilter: null,
      sort: { column: "archived", direction: "asc" },
    });
    expect(result.map((i) => i.archived.taskId)).toEqual(["a", "b"]);
  });
});
