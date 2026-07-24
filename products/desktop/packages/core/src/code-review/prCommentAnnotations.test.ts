import type { PrReviewComment } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import { buildFileAnnotations } from "./prCommentAnnotations";
import type { PrCommentMetadata, PrCommentThread } from "./types";

function makeThread(
  rootComment: Partial<PrReviewComment>,
  overrides: Partial<PrCommentThread> = {},
): PrCommentThread {
  return {
    rootId: 1,
    nodeId: "n1",
    isResolved: false,
    filePath: "a.ts",
    comments: [rootComment as PrReviewComment],
    ...overrides,
  };
}

describe("buildFileAnnotations", () => {
  it("filters threads to the requested file path", () => {
    const threads = new Map<number, PrCommentThread>([
      [1, makeThread({ line: 5 })],
      [2, makeThread({ line: 6 }, { rootId: 2, filePath: "b.ts" })],
    ]);
    expect(buildFileAnnotations(threads, "a.ts")).toHaveLength(1);
  });

  it("derives a deletions side for LEFT comments", () => {
    const threads = new Map<number, PrCommentThread>([
      [1, makeThread({ line: 5, side: "LEFT" })],
    ]);
    const [annotation] = buildFileAnnotations(threads, "a.ts");
    expect(annotation.side).toBe("deletions");
  });

  it("treats a comment with no line/original_line as file-level", () => {
    const threads = new Map<number, PrCommentThread>([
      [1, makeThread({ line: null, original_line: null })],
    ]);
    const [annotation] = buildFileAnnotations(threads, "a.ts");
    const meta = annotation.metadata as PrCommentMetadata;
    expect(meta.isFileLevel).toBe(true);
    expect(annotation.lineNumber).toBe(1);
  });

  it("marks an outdated comment when only original_line is present", () => {
    const threads = new Map<number, PrCommentThread>([
      [1, makeThread({ line: null, original_line: 12 })],
    ]);
    const [annotation] = buildFileAnnotations(threads, "a.ts");
    const meta = annotation.metadata as PrCommentMetadata;
    expect(meta.isOutdated).toBe(true);
    expect(annotation.lineNumber).toBe(12);
  });
});
