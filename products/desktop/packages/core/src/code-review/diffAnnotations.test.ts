import type { FileDiffMetadata } from "@pierre/diffs";
import { describe, expect, it } from "vitest";
import {
  buildCommentMergedOptions,
  buildDraftAnnotations,
  buildHunkAnnotations,
  getLastChangeLineNumber,
} from "./diffAnnotations";
import type { DraftComment } from "./types";

type Hunk = FileDiffMetadata["hunks"][number];

function makeHunk(overrides: Partial<Hunk>): Hunk {
  return {
    additionStart: 1,
    additionLines: 0,
    deletionLines: 0,
    hunkContent: [],
    ...overrides,
  } as Hunk;
}

describe("getLastChangeLineNumber", () => {
  it("computes the last changed line accounting for context offset", () => {
    const hunk = makeHunk({
      additionStart: 10,
      hunkContent: [
        { type: "context", lines: 2 },
        { type: "change", additions: 3 },
      ] as Hunk["hunkContent"],
    });
    expect(getLastChangeLineNumber(hunk)).toBe(14);
  });
});

describe("buildHunkAnnotations", () => {
  it("skips empty hunks and emits a revert annotation per changed hunk", () => {
    const fileDiff = {
      hunks: [
        makeHunk({ additionLines: 0, deletionLines: 0 }),
        makeHunk({
          additionStart: 5,
          additionLines: 1,
          hunkContent: [
            { type: "change", additions: 1 },
          ] as Hunk["hunkContent"],
        }),
      ],
    } as FileDiffMetadata;

    const annotations = buildHunkAnnotations(fileDiff);
    expect(annotations).toHaveLength(1);
    expect(annotations[0].metadata).toEqual({
      kind: "hunk-revert",
      hunkIndex: 1,
    });
    expect(annotations[0].side).toBe("additions");
  });
});

describe("buildDraftAnnotations", () => {
  it("maps drafts to draft-comment annotations on their side/endLine", () => {
    const drafts: DraftComment[] = [
      {
        id: "d1",
        taskId: "t",
        filePath: "a.ts",
        startLine: 2,
        endLine: 4,
        side: "deletions",
        text: "x",
        createdAt: 0,
      },
    ];
    const [annotation] = buildDraftAnnotations(drafts);
    expect(annotation.side).toBe("deletions");
    expect(annotation.lineNumber).toBe(4);
    expect(annotation.metadata).toMatchObject({
      kind: "draft-comment",
      draftId: "d1",
    });
  });
});

describe("buildCommentMergedOptions", () => {
  it.each([
    { hasOpenComment: false, expectedEnabled: true },
    { hasOpenComment: true, expectedEnabled: false },
  ])(
    "with hasOpenComment=$hasOpenComment sets selection/gutter enabled=$expectedEnabled and routes callbacks to the handlers",
    ({ hasOpenComment, expectedEnabled }) => {
      const onChange = () => {};
      const onEnd = () => {};
      const merged = buildCommentMergedOptions(
        undefined,
        hasOpenComment,
        onChange,
        onEnd,
      );
      expect(merged.enableLineSelection).toBe(expectedEnabled);
      expect(merged.enableGutterUtility).toBe(expectedEnabled);
      expect(merged.onLineSelectionChange).toBe(onChange);
      expect(merged.onLineSelectionEnd).toBe(onEnd);
      expect(merged.onGutterUtilityClick).toBe(onEnd);
    },
  );
});
