import { describe, expect, it } from "vitest";
import {
  formatTaskContext,
  type TaskContextFolder,
  type TaskContextTask,
} from "./taskContext";

const CODE_REPO = {
  fullPath: "posthog/code",
  name: "code",
  organization: "PostHog",
};

function task(overrides: Partial<TaskContextTask> = {}): TaskContextTask {
  return {
    repository: CODE_REPO,
    workspaceMode: "local",
    branchName: null,
    linkedBranch: null,
    ...overrides,
  };
}

const mainClone: TaskContextFolder = {
  name: "PostHog Desktop",
  path: "/repos/code",
  remoteUrl: "posthog/code",
  mainRepoPath: null,
};

describe("formatTaskContext", () => {
  it.each<{ name: string; task: TaskContextTask; expected: string | null }>([
    {
      name: "repository only when the task has no branch of its own",
      task: task(),
      expected: "code",
    },
    {
      name: "repository and linked branch",
      task: task({ linkedBranch: "posthog-code/fix-login" }),
      expected: "code · posthog-code/fix-login",
    },
    {
      name: "the worktree's checked-out branch when no branch is linked yet",
      task: task({ workspaceMode: "worktree", branchName: "wt/parser" }),
      expected: "code · wt/parser",
    },
    {
      name: "the linked branch in preference to the checked-out branch",
      task: task({
        workspaceMode: "worktree",
        branchName: "wt/parser",
        linkedBranch: "posthog-code/parser",
      }),
      expected: "code · posthog-code/parser",
    },
    {
      name: "no branch for a local task sitting on the default branch",
      // A local workspace reports whatever branch the checkout is on, which is
      // shared by every local task in the repo. Only `linkedBranch` is the
      // task's own, so `main` must not leak into the line.
      task: task({ workspaceMode: "local", branchName: "main" }),
      expected: "code",
    },
    {
      name: "repository only for a cloud task with no linked branch",
      task: task({ workspaceMode: "cloud" }),
      expected: "code",
    },
    {
      name: "the custom-images group name for image-builder tasks",
      task: task({ repository: null, originProduct: "image_builder" }),
      expected: "Custom images",
    },
    {
      name: "the branch alone when the task has no repository",
      task: task({ repository: null, linkedBranch: "posthog-code/orphan" }),
      expected: "posthog-code/orphan",
    },
    {
      name: "null when there is neither a repository nor a branch",
      task: task({ repository: null }),
      expected: null,
    },
  ])("renders $name", ({ task: subject, expected }) => {
    expect(formatTaskContext(subject)).toBe(expected);
  });

  it("labels the repository with the registered folder's name", () => {
    expect(formatTaskContext(task(), [mainClone])).toBe("PostHog Desktop");
  });

  it("labels a worktree task with its main checkout's folder name", () => {
    const worktree: TaskContextFolder = {
      name: "code-wt",
      path: "/repos/code-wt",
      remoteUrl: "posthog/code",
      mainRepoPath: "/repos/code",
    };

    expect(
      formatTaskContext(
        task({ workspaceMode: "worktree", branchName: "wt/parser" }),
        [worktree, mainClone],
      ),
    ).toBe("PostHog Desktop · wt/parser");
  });

  it("falls back to the repository name when no folder is registered", () => {
    const unrelated: TaskContextFolder = {
      name: "posthog",
      path: "/repos/posthog",
      remoteUrl: "posthog/posthog",
      mainRepoPath: null,
    };

    expect(formatTaskContext(task(), [unrelated])).toBe("code");
  });
});
