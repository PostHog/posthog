import { describe, expect, it } from "vitest";
import { findCloneForRepo, isRepoCloning } from "./cloneSelectors";
import type { CloneOperation } from "./cloneTypes";

const op = (overrides: Partial<CloneOperation>): CloneOperation => ({
  cloneId: "c1",
  repository: "owner/repo",
  targetPath: "/tmp/repo",
  status: "cloning",
  ...overrides,
});

describe("isRepoCloning", () => {
  it("is false when no operation matches the repo", () => {
    expect(isRepoCloning({}, "owner/repo")).toBe(false);
  });

  it("is true while a matching operation is cloning", () => {
    const ops = { c1: op({}) };
    expect(isRepoCloning(ops, "owner/repo")).toBe(true);
  });

  it("is false once the matching operation is complete", () => {
    const ops = { c1: op({ status: "complete" }) };
    expect(isRepoCloning(ops, "owner/repo")).toBe(false);
  });
});

describe("findCloneForRepo", () => {
  it("returns null when no operation matches", () => {
    expect(findCloneForRepo({}, "owner/repo")).toBeNull();
  });

  it("returns the operation for the repo", () => {
    const ops = { c1: op({}) };
    expect(findCloneForRepo(ops, "owner/repo")?.cloneId).toBe("c1");
  });
});
