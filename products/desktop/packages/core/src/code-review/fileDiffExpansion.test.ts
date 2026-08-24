import type { FileDiffMetadata } from "@pierre/diffs";
import { describe, expect, it } from "vitest";
import { buildExpandedFileDiff, canExpandFileDiff } from "./fileDiffExpansion";

function makePatch(
  overrides: Partial<FileDiffMetadata> = {},
): FileDiffMetadata {
  return {
    name: "foo.ts",
    type: "change",
    hunks: [],
    splitLineCount: 0,
    unifiedLineCount: 0,
    isPartial: true,
    deletionLines: [],
    additionLines: [],
    ...overrides,
  } as FileDiffMetadata;
}

describe("canExpandFileDiff", () => {
  it("returns false when skip is true", () => {
    expect(canExpandFileDiff(makePatch(), "/repo", true)).toBe(false);
  });

  it("returns false when repoPath is missing", () => {
    expect(canExpandFileDiff(makePatch(), undefined, false)).toBe(false);
  });

  it("returns false for deleted files", () => {
    expect(
      canExpandFileDiff(makePatch({ type: "deleted" }), "/repo", false),
    ).toBe(false);
  });

  it("returns false for pure renames", () => {
    expect(
      canExpandFileDiff(makePatch({ type: "rename-pure" }), "/repo", false),
    ).toBe(false);
  });

  it("returns true for normal change with repo", () => {
    expect(canExpandFileDiff(makePatch(), "/repo", false)).toBe(true);
  });
});

describe("buildExpandedFileDiff", () => {
  it("returns original patch when content undefined", () => {
    const patch = makePatch();
    expect(buildExpandedFileDiff(patch, undefined, "new")).toBe(patch);
    expect(buildExpandedFileDiff(patch, "old", undefined)).toBe(patch);
  });

  it("produces a non-partial diff when both contents provided", () => {
    const patch = makePatch();
    const result = buildExpandedFileDiff(patch, "a\nb\nc\n", "a\nB\nc\n");
    expect(result).not.toBe(patch);
    expect(result.isPartial).toBe(false);
  });

  it("treats null content as empty string", () => {
    const patch = makePatch({ type: "new" });
    const result = buildExpandedFileDiff(patch, null, "hello\n");
    expect(result.isPartial).toBe(false);
  });
});
