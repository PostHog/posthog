import type { Task } from "@posthog/shared/domain-types";
import { describe, expect, it } from "vitest";
import {
  findGroupFolder,
  type GroupableTask,
  getRepositoryInfo,
  groupByRepository,
  type TaskRepositoryInfo,
} from "./groupTasks";

interface TestTask extends GroupableTask {
  id: string;
}

function makeTask(overrides: Partial<Task> = {}): Task {
  return {
    id: "task-1",
    title: "Test task",
    description: "",
    repository: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-02T00:00:00Z",
    ...overrides,
  } as Task;
}

function task(
  id: string,
  repository: TaskRepositoryInfo | null = null,
): TestTask {
  return { id, repository };
}

describe("getRepositoryInfo", () => {
  it("returns lowercased owner/repo fullPath for a structured repository", () => {
    const info = getRepositoryInfo(makeTask({ repository: "PostHog/code" }));
    expect(info).toEqual({
      fullPath: "posthog/code",
      name: "code",
      organization: "PostHog",
    });
  });

  it("strips .git suffix from both fullPath and name", () => {
    const info = getRepositoryInfo(
      makeTask({ repository: "PostHog/code.git" }),
    );
    expect(info).toEqual({
      fullPath: "posthog/code",
      name: "code",
      organization: "PostHog",
    });
  });

  it("strips .git suffix even when repository is already lowercase", () => {
    const info = getRepositoryInfo(
      makeTask({ repository: "posthog/code.git" }),
    );
    expect(info).toEqual({
      fullPath: "posthog/code",
      name: "code",
      organization: "posthog",
    });
  });

  it("trims surrounding whitespace from the repository string", () => {
    const info = getRepositoryInfo(
      makeTask({ repository: "  PostHog/code.git\n" }),
    );
    expect(info).toEqual({
      fullPath: "posthog/code",
      name: "code",
      organization: "PostHog",
    });
  });

  it("falls through to the folderPath when the repository string is malformed", () => {
    const info = getRepositoryInfo(
      makeTask({ repository: "posthog" }),
      "/Users/test/projects/custom",
    );
    expect(info).toEqual({
      fullPath: "/Users/test/projects/custom",
      name: "custom",
    });
  });

  it("returns null for a malformed repository without a folderPath", () => {
    const info = getRepositoryInfo(makeTask({ repository: "posthog" }));
    expect(info).toBeNull();
  });

  it("returns null when both repository and folderPath are absent", () => {
    const info = getRepositoryInfo(makeTask({ repository: null }));
    expect(info).toBeNull();
  });

  it("uses the folderPath when repository is null", () => {
    const info = getRepositoryInfo(
      makeTask({ repository: null }),
      "/Users/test/projects/my-repo",
    );
    expect(info).toEqual({
      fullPath: "/Users/test/projects/my-repo",
      name: "my-repo",
    });
  });
});

describe("groupByRepository", () => {
  it("returns an empty array for an empty task list", () => {
    const groups = groupByRepository([], []);
    expect(groups).toEqual([]);
  });

  it("produces both repo groups and an 'other' group for mixed tasks", () => {
    const tasks: TestTask[] = [
      task("t1", {
        fullPath: "posthog/code",
        name: "code",
        organization: "PostHog",
      }),
      task("t2"),
    ];

    const groups = groupByRepository(tasks, []);

    expect(groups).toHaveLength(2);
    const byId = new Map(groups.map((g) => [g.id, g]));
    expect(byId.get("posthog/code")?.tasks).toHaveLength(1);
    expect(byId.get("other")?.tasks).toHaveLength(1);
  });

  it("merges .git and non-.git variants of the same repository into one group", () => {
    // Exercises the end-to-end flow: getRepositoryInfo normalizes both, then
    // groupByRepository sees them as the same bucket.
    const t1 = getRepositoryInfo(makeTask({ repository: "PostHog/code.git" }));
    const t2 = getRepositoryInfo(makeTask({ repository: "posthog/code" }));
    expect(t1).not.toBeNull();
    expect(t2).not.toBeNull();

    const groups = groupByRepository([task("t1", t1), task("t2", t2)], []);

    expect(groups).toHaveLength(1);
    expect(groups[0]?.id).toBe("posthog/code");
    expect(groups[0]?.name).toBe("code");
    expect(groups[0]?.tasks.map((t) => t.id)).toEqual(["t1", "t2"]);
  });

  it("merges tasks with the same repository but different casing into one group", () => {
    const tasks: TestTask[] = [
      task("t1", {
        fullPath: "posthog/code",
        name: "code",
        organization: "PostHog",
      }),
      task("t2", {
        fullPath: "posthog/code",
        name: "code",
        organization: "posthog",
      }),
    ];

    const groups = groupByRepository(tasks, []);

    expect(groups).toHaveLength(1);
    expect(groups[0]?.id).toBe("posthog/code");
    expect(groups[0]?.tasks.map((t) => t.id)).toEqual(["t1", "t2"]);
  });

  it("keeps distinct repositories in distinct groups", () => {
    const tasks: TestTask[] = [
      task("t1", {
        fullPath: "posthog/posthog",
        name: "posthog",
        organization: "PostHog",
      }),
      task("t2", {
        fullPath: "posthog/code",
        name: "code",
        organization: "PostHog",
      }),
    ];

    const groups = groupByRepository(tasks, []);

    expect(groups).toHaveLength(2);
    const byId = new Map(groups.map((g) => [g.id, g]));
    expect(byId.get("posthog/code")?.name).toBe("code");
    expect(byId.get("posthog/posthog")?.name).toBe("posthog");
  });

  it("prefixes the organization when two groups share a display name", () => {
    const tasks: TestTask[] = [
      task("t1", {
        fullPath: "posthog/shared",
        name: "shared",
        organization: "PostHog",
      }),
      task("t2", {
        fullPath: "acme/shared",
        name: "shared",
        organization: "acme",
      }),
    ];

    const groups = groupByRepository(tasks, []);

    expect(groups).toHaveLength(2);
    const names = new Set(groups.map((g) => g.name));
    expect(names).toEqual(new Set(["PostHog/shared", "acme/shared"]));
  });

  it("routes tasks with no repository info to the 'other' group", () => {
    const tasks: TestTask[] = [task("t1"), task("t2")];

    const groups = groupByRepository(tasks, []);

    expect(groups).toHaveLength(1);
    expect(groups[0]?.id).toBe("other");
    expect(groups[0]?.name).toBe("Other");
  });

  it("routes image-builder tasks to a pinned 'Custom images' group above 'Other'", () => {
    const tasks: TestTask[] = [
      { id: "t1", repository: null, originProduct: "image_builder" },
      {
        id: "t2",
        repository: {
          fullPath: "posthog/code",
          name: "code",
          organization: "PostHog",
        },
        originProduct: "image_builder",
      },
      task("t3"),
      task("t4", {
        fullPath: "posthog/posthog",
        name: "posthog",
        organization: "PostHog",
      }),
    ];

    const groups = groupByRepository(tasks, []);

    expect(groups.map((g) => g.id)).toEqual([
      "posthog/posthog",
      "custom-images",
      "other",
    ]);
    expect(groups[1]?.name).toBe("Custom images");
    expect(groups[1]?.tasks.map((t) => t.id)).toEqual(["t1", "t2"]);
  });

  it("keeps the bare name for a group without an organization when others collide", () => {
    const tasks: TestTask[] = [
      task("t1", {
        fullPath: "posthog/shared",
        name: "shared",
        organization: "PostHog",
      }),
      task("t2", {
        fullPath: "acme/shared",
        name: "shared",
        organization: "acme",
      }),
      task("t3", { fullPath: "/Users/dev/shared", name: "shared" }),
    ];

    const groups = groupByRepository(tasks, []);
    const names = groups.map((g) => g.name).sort();

    expect(names).toEqual(["PostHog/shared", "acme/shared", "shared"]);
  });

  it("respects the provided folder order", () => {
    const tasks: TestTask[] = [
      task("t1", {
        fullPath: "posthog/code",
        name: "code",
        organization: "PostHog",
      }),
      task("t2", {
        fullPath: "posthog/posthog",
        name: "posthog",
        organization: "PostHog",
      }),
    ];

    const groups = groupByRepository(tasks, [
      "posthog/posthog",
      "posthog/code",
    ]);

    expect(groups.map((g) => g.id)).toEqual([
      "posthog/posthog",
      "posthog/code",
    ]);
  });

  it("places ordered groups first, then unknown groups alphabetically", () => {
    const tasks: TestTask[] = [
      task("t1", {
        fullPath: "posthog/code",
        name: "code",
        organization: "PostHog",
      }),
      task("t2", {
        fullPath: "posthog/posthog",
        name: "posthog",
        organization: "PostHog",
      }),
      task("t3", {
        fullPath: "acme/alpha",
        name: "alpha",
        organization: "acme",
      }),
      task("t4", {
        fullPath: "acme/zeta",
        name: "zeta",
        organization: "acme",
      }),
    ];

    const groups = groupByRepository(tasks, ["posthog/posthog"]);

    expect(groups.map((g) => g.id)).toEqual([
      "posthog/posthog",
      "acme/alpha",
      "posthog/code",
      "acme/zeta",
    ]);
  });

  it("sorts the 'other' group last in the alphabetical path", () => {
    const tasks: TestTask[] = [
      task("t1"),
      task("t2", {
        fullPath: "posthog/zeta",
        name: "zeta",
        organization: "PostHog",
      }),
      task("t3", {
        fullPath: "posthog/alpha",
        name: "alpha",
        organization: "PostHog",
      }),
    ];

    const groups = groupByRepository(tasks, []);

    expect(groups.map((g) => g.id)).toEqual([
      "posthog/alpha",
      "posthog/zeta",
      "other",
    ]);
  });

  it("sorts the 'other' group last in the folder-order path", () => {
    const tasks: TestTask[] = [
      task("t1"),
      task("t2", {
        fullPath: "posthog/code",
        name: "code",
        organization: "PostHog",
      }),
      task("t3", {
        fullPath: "posthog/posthog",
        name: "posthog",
        organization: "PostHog",
      }),
    ];

    const groups = groupByRepository(tasks, [
      "posthog/posthog",
      "posthog/code",
    ]);

    expect(groups.map((g) => g.id)).toEqual([
      "posthog/posthog",
      "posthog/code",
      "other",
    ]);
  });
});

describe("findGroupFolder", () => {
  interface GroupFolder {
    path: string;
    remoteUrl: string | null;
    mainRepoPath?: string | null;
  }

  const mainClone: GroupFolder = {
    path: "/repos/code",
    remoteUrl: "posthog/code",
    mainRepoPath: null,
  };
  const worktree: GroupFolder = {
    path: "/repos/code-wt",
    remoteUrl: "posthog/code",
    mainRepoPath: "/repos/code",
  };
  const unrelated: GroupFolder = {
    path: "/repos/other",
    remoteUrl: "acme/other",
    mainRepoPath: null,
  };
  const local: GroupFolder = { path: "/repos/local", remoteUrl: null };

  it.each<{
    name: string;
    folders: GroupFolder[];
    groupId: string;
    expected: GroupFolder | undefined;
  }>([
    {
      name: "prefers the main clone when a worktree of the same repo was added first",
      folders: [worktree, mainClone, unrelated],
      groupId: "posthog/code",
      expected: mainClone,
    },
    {
      name: "falls back to the worktree when only it is registered",
      folders: [worktree, unrelated],
      groupId: "posthog/code",
      expected: worktree,
    },
    {
      name: "matches folders without a remote by path",
      folders: [local],
      groupId: "/repos/local",
      expected: local,
    },
    {
      name: "returns undefined when nothing matches",
      folders: [unrelated],
      groupId: "posthog/code",
      expected: undefined,
    },
  ])("$name", ({ folders, groupId, expected }) => {
    expect(findGroupFolder(folders, groupId)).toBe(expected);
  });
});
