import { describe, expect, it } from "vitest";
import { buildWorktreeAdoptionInput, prepareTaskInput } from "./taskInput";

describe("prepareTaskInput", () => {
  // The isCloud guard on customInstructions is the only thing preventing
  // double-injection: local tasks already receive personalization via the
  // workspace-server system prompt, so the field must be dropped for them and
  // only passed through for cloud.
  it.each([
    { workspaceMode: "cloud" as const, expected: "Always use tabs." },
    { workspaceMode: "local" as const, expected: undefined },
    { workspaceMode: "worktree" as const, expected: undefined },
  ])(
    "passes customInstructions through only for cloud (%s)",
    ({ workspaceMode, expected }) => {
      const input = prepareTaskInput("do the thing", [], {
        workspaceMode,
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

  it("drops customInstructions for cloud when none is set", () => {
    const input = prepareTaskInput("do the thing", [], {
      workspaceMode: "cloud",
    });
    expect(input.customInstructions).toBeUndefined();
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
