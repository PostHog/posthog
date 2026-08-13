import type { ChangedFile } from "@posthog/shared/domain-types";
import { describe, expect, it } from "vitest";
import { deriveCreatePrPlan, deriveStagingPlan } from "./stagingPlan";

function file(path: string, staged: boolean): ChangedFile {
  return { path, status: "modified", staged } as ChangedFile;
}

describe("deriveStagingPlan", () => {
  it("flags stagedOnly when both staged and unstaged exist and commitAll is off", () => {
    const plan = deriveStagingPlan(
      [file("a", true)],
      [file("b", false)],
      false,
    );
    expect(plan.stagedOnly).toBe(true);
    expect(plan.stagingContext.staged_only).toBe(true);
  });

  it("does not flag stagedOnly when commitAll is on", () => {
    const plan = deriveStagingPlan([file("a", true)], [file("b", false)], true);
    expect(plan.stagedOnly).toBe(false);
  });

  it("does not flag stagedOnly when only staged files exist", () => {
    const plan = deriveStagingPlan([file("a", true)], [], false);
    expect(plan.stagedOnly).toBe(false);
  });

  it("tallies file counts and commit_all", () => {
    const plan = deriveStagingPlan(
      [file("a", true), file("b", true)],
      [file("c", false)],
      true,
    );
    expect(plan.stagingContext).toEqual({
      staged_file_count: 2,
      unstaged_file_count: 1,
      commit_all: true,
      staged_only: false,
    });
  });
});

describe("deriveCreatePrPlan", () => {
  it("needs a branch when not on a feature branch", () => {
    const plan = deriveCreatePrPlan({
      isFeatureBranch: false,
      prExists: false,
      hasChanges: true,
      stagedFileCount: 0,
      unstagedFileCount: 1,
    });
    expect(plan.needsBranch).toBe(true);
    expect(plan.needsCommit).toBe(true);
  });

  it("needs a branch when a PR already exists even on a feature branch", () => {
    const plan = deriveCreatePrPlan({
      isFeatureBranch: true,
      prExists: true,
      hasChanges: false,
      stagedFileCount: 0,
      unstagedFileCount: 0,
    });
    expect(plan.needsBranch).toBe(true);
  });

  it("does not need a branch on a feature branch with no PR", () => {
    const plan = deriveCreatePrPlan({
      isFeatureBranch: true,
      prExists: false,
      hasChanges: true,
      stagedFileCount: 1,
      unstagedFileCount: 0,
    });
    expect(plan.needsBranch).toBe(false);
  });

  it("disables commitAll when staging is mixed", () => {
    const plan = deriveCreatePrPlan({
      isFeatureBranch: true,
      prExists: false,
      hasChanges: true,
      stagedFileCount: 1,
      unstagedFileCount: 1,
    });
    expect(plan.commitAll).toBe(false);
  });
});
