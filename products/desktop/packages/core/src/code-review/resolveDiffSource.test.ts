import { describe, expect, it } from "vitest";
import {
  type ResolveDiffSourceInput,
  type ResolvedDiffSource,
  resolveDiffSource,
} from "./resolveDiffSource";

describe("resolveDiffSource", () => {
  it.each<
    ResolveDiffSourceInput & { expected: ResolvedDiffSource; desc: string }
  >([
    // Heuristic (no user choice) — dirty > pr > branch > local.
    {
      desc: "heuristic: uncommitted changes → local (even with PR)",
      configured: null,
      hasLocalChanges: true,
      linkedBranch: "feat/x",
      aheadOfDefault: 3,
      prSourceAvailable: true,
      expected: "local",
    },
    {
      desc: "heuristic: clean tree with PR → pr",
      configured: null,
      hasLocalChanges: false,
      linkedBranch: "feat/x",
      aheadOfDefault: 2,
      prSourceAvailable: true,
      expected: "pr",
    },
    {
      desc: "heuristic: clean tree with commits ahead (no PR) → branch",
      configured: null,
      hasLocalChanges: false,
      linkedBranch: "feat/x",
      aheadOfDefault: 2,
      prSourceAvailable: false,
      expected: "branch",
    },
    {
      desc: "heuristic: no linked branch, no PR → local",
      configured: null,
      hasLocalChanges: false,
      linkedBranch: null,
      aheadOfDefault: 0,
      prSourceAvailable: false,
      expected: "local",
    },
    {
      desc: "heuristic: linked branch but no commits ahead, no PR → local",
      configured: null,
      hasLocalChanges: false,
      linkedBranch: "feat/x",
      aheadOfDefault: 0,
      prSourceAvailable: false,
      expected: "local",
    },
    // Explicit local.
    {
      desc: "explicit local respected even when PR is available",
      configured: "local",
      hasLocalChanges: false,
      linkedBranch: "feat/x",
      aheadOfDefault: 5,
      prSourceAvailable: true,
      expected: "local",
    },
    // Explicit branch.
    {
      desc: "explicit branch respected when available",
      configured: "branch",
      hasLocalChanges: true,
      linkedBranch: "feat/x",
      aheadOfDefault: 1,
      prSourceAvailable: false,
      expected: "branch",
    },
    {
      desc: "explicit branch falls back to local when unavailable",
      configured: "branch",
      hasLocalChanges: false,
      linkedBranch: null,
      aheadOfDefault: 0,
      prSourceAvailable: false,
      expected: "local",
    },
    // Explicit pr.
    {
      desc: "explicit pr respected when available",
      configured: "pr",
      hasLocalChanges: true,
      linkedBranch: "feat/x",
      aheadOfDefault: 1,
      prSourceAvailable: true,
      expected: "pr",
    },
    {
      desc: "explicit pr falls back to branch when PR unavailable but branch is",
      configured: "pr",
      hasLocalChanges: false,
      linkedBranch: "feat/x",
      aheadOfDefault: 3,
      prSourceAvailable: false,
      expected: "branch",
    },
    {
      desc: "explicit pr falls back to local when nothing else available",
      configured: "pr",
      hasLocalChanges: false,
      linkedBranch: null,
      aheadOfDefault: 0,
      prSourceAvailable: false,
      expected: "local",
    },
  ])("$desc", ({ expected, ...input }) => {
    expect(resolveDiffSource(input)).toBe(expected);
  });
});
