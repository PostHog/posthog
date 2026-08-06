import type { ChangedFile } from "@posthog/shared/domain-types";
import { describe, expect, it, vi } from "vitest";
import {
  deriveIsCloud,
  EMPTY_DIFF_STATS,
  selectTaskDiffStats,
} from "./selectTaskDiffStats";

function makeFiles(paths: string[]): ChangedFile[] {
  return paths.map((path) => ({ path }) as ChangedFile);
}

const compute = vi.fn((files: ChangedFile[]) => ({
  filesChanged: files.length,
  linesAdded: files.length,
  linesRemoved: 0,
}));

describe("deriveIsCloud", () => {
  it("is true when workspace mode is cloud", () => {
    expect(deriveIsCloud("cloud", undefined)).toBe(true);
  });

  it("is true when latest run environment is cloud", () => {
    expect(deriveIsCloud("local", "cloud")).toBe(true);
  });

  it("is false otherwise", () => {
    expect(deriveIsCloud("local", "local")).toBe(false);
  });
});

describe("selectTaskDiffStats", () => {
  const base = {
    reviewFiles: makeFiles(["r1", "r2"]),
    branchFiles: makeFiles(["b1"]),
    prFiles: makeFiles(["p1", "p2", "p3"]),
    localDiffStats: { filesChanged: 9, linesAdded: 9, linesRemoved: 9 },
    computeStats: compute,
  };

  it("uses reviewFiles when cloud", () => {
    expect(
      selectTaskDiffStats({ ...base, isCloud: true, effectiveSource: "pr" })
        .filesChanged,
    ).toBe(2);
  });

  it("uses branchFiles for branch source", () => {
    expect(
      selectTaskDiffStats({
        ...base,
        isCloud: false,
        effectiveSource: "branch",
      }).filesChanged,
    ).toBe(1);
  });

  it("falls back to empty stats when branch files missing", () => {
    expect(
      selectTaskDiffStats({
        ...base,
        isCloud: false,
        effectiveSource: "branch",
        branchFiles: undefined,
      }),
    ).toBe(EMPTY_DIFF_STATS);
  });

  it("uses prFiles for pr source", () => {
    expect(
      selectTaskDiffStats({ ...base, isCloud: false, effectiveSource: "pr" })
        .filesChanged,
    ).toBe(3);
  });

  it("returns localDiffStats for local source", () => {
    expect(
      selectTaskDiffStats({
        ...base,
        isCloud: false,
        effectiveSource: "local",
      }),
    ).toBe(base.localDiffStats);
  });
});
