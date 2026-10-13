import { describe, expect, it } from "vitest";
import { buildWorktreeAdoptionInput, prepareTaskInput } from "./taskInput";

describe("prepareTaskInput", () => {
  // Local ACP reads personalization through its workspace-server prompt. Pi
  // bypasses that path, so it needs the task input to carry the instructions.
  it.each([
    {
      workspaceMode: "cloud" as const,
      runtime: "acp" as const,
      expected: "Always use tabs.",
    },
    {
      workspaceMode: "local" as const,
      runtime: "acp" as const,
      expected: undefined,
    },
    {
      workspaceMode: "worktree" as const,
      runtime: "acp" as const,
      expected: undefined,
    },
    {
      workspaceMode: "local" as const,
      runtime: "pi" as const,
      expected: "Always use tabs.",
    },
    {
      workspaceMode: "worktree" as const,
      runtime: "pi" as const,
      expected: "Always use tabs.",
    },
  ])(
    "passes customInstructions through for cloud and Pi tasks",
    ({ workspaceMode, runtime, expected }) => {
      const input = prepareTaskInput("do the thing", [], {
        workspaceMode,
        runtime,
        customInstructions: "Always use tabs.",
      });
      expect(input.customInstructions).toBe(expected);
    },
  );

  it("defaults task creation to the ACP runtime", () => {
    const input = prepareTaskInput("do the thing", [], {
      workspaceMode: "local",
    });

    expect(input.runtime).toBe("acp");
  });

  it("preserves the selected Pi runtime", () => {
    const input = prepareTaskInput("do the thing", [], {
      workspaceMode: "local",
      runtime: "pi",
    });

    expect(input.runtime).toBe("pi");
  });

  it("preserves the selected Codex model access", () => {
    const input = prepareTaskInput("do the thing", [], {
      workspaceMode: "local",
      adapter: "codex",
      codexModelAccess: "own-subscription",
    });

    expect(input.codexModelAccess).toBe("own-subscription");
  });

  it("preserves the selected Claude model access", () => {
    const input = prepareTaskInput("do the thing", [], {
      workspaceMode: "local",
      adapter: "claude",
      claudeModelAccess: "own-subscription",
    });

    expect(input.claudeModelAccess).toBe("own-subscription");
  });

  it("drops customInstructions for cloud when none is set", () => {
    const input = prepareTaskInput("do the thing", [], {
      workspaceMode: "cloud",
    });
    expect(input.customInstructions).toBeUndefined();
  });

  it("preserves task-specific cloud repositories", () => {
    const input = prepareTaskInput("do the thing", [], {
      workspaceMode: "cloud",
      repositories: ["posthog/posthog", "posthog/posthog-js"],
      githubIntegrationId: 42,
    });

    expect(input.repositories).toEqual([
      "posthog/posthog",
      "posthog/posthog-js",
    ]);
    expect(input.githubIntegrationId).toBe(42);
  });

  it("uses a selected folder for a repo-optional local task", () => {
    const input = prepareTaskInput("do the thing", [], {
      workspaceMode: "local",
      selectedDirectory: "/code/posthog",
      allowNoRepo: true,
    });

    expect(input.repoPath).toBe("/code/posthog");
  });
});

describe("buildWorktreeAdoptionInput", () => {
  it("builds a promptless worktree input that adopts the branch's worktree", () => {
    const input = buildWorktreeAdoptionInput({
      repoPath: "/repo",
      branch: "feature/orphan",
    });

    expect(input).toEqual({
      taskDescription: "feature/orphan",
      repoPath: "/repo",
      workspaceMode: "worktree",
      branch: "feature/orphan",
      reuseExistingWorktree: true,
    });
    // No content: the saga must not build an initial prompt, so the agent
    // session starts idle in the adopted worktree.
    expect(input.content).toBeUndefined();
  });
});
