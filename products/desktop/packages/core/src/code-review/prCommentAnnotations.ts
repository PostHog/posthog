import type { DiffLineAnnotation } from "@pierre/diffs";
import type { AnnotationMetadata, PrCommentThread } from "./types";

export type { PrCommentThread } from "./types";

function buildAnnotation(
  thread: PrCommentThread,
): DiffLineAnnotation<AnnotationMetadata> | null {
  const root = thread.comments[0];
  if (!root) return null;

  const isFileLevel = root.line == null && root.original_line == null;
  const line = root.line ?? root.original_line ?? 1;

  const isOutdated =
    !isFileLevel && root.line == null && root.original_line != null;
  const side = isFileLevel
    ? "additions"
    : root.side === "LEFT"
      ? "deletions"
      : "additions";

  return {
    side,
    lineNumber: line,
    metadata: {
      kind: "pr-comment",
      threadId: thread.rootId,
      nodeId: thread.nodeId,
      isResolved: thread.isResolved,
      comments: thread.comments,
      isOutdated,
      isFileLevel,
      startLine: root.start_line,
      endLine: line,
      side,
    },
  };
}

export function buildFileAnnotations(
  threads: Map<number, PrCommentThread>,
  filePath: string,
): DiffLineAnnotation<AnnotationMetadata>[] {
  const annotations: DiffLineAnnotation<AnnotationMetadata>[] = [];
  for (const thread of threads.values()) {
    if (thread.filePath !== filePath) continue;
    const annotation = buildAnnotation(thread);
    if (annotation) annotations.push(annotation);
  }
  return annotations;
}
