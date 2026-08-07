import type {
  AnnotationSide,
  DiffLineAnnotation,
  SelectedLineRange,
} from "@pierre/diffs";
import type { AnnotationMetadata } from "@posthog/ui/features/code-review/types";
import { useCallback, useState } from "react";

export interface CommentEditSeed {
  draftId: string;
  text: string;
  filePath: string;
  startLine: number;
  endLine: number;
  side: AnnotationSide;
}

export function useCommentState() {
  const [selectedRange, setSelectedRange] = useState<SelectedLineRange | null>(
    null,
  );
  const [commentAnnotation, setCommentAnnotation] =
    useState<DiffLineAnnotation<AnnotationMetadata> | null>(null);
  const [editSeed, setEditSeed] = useState<CommentEditSeed | null>(null);

  const hasOpenComment = commentAnnotation !== null;

  const reset = useCallback(() => {
    setCommentAnnotation(null);
    setSelectedRange(null);
    setEditSeed(null);
  }, []);

  const handleLineSelectionChange = useCallback(
    (range: SelectedLineRange | null) => {
      setSelectedRange(range);
    },
    [],
  );

  const handleLineSelectionEnd = useCallback(
    (range: SelectedLineRange | null) => {
      setSelectedRange(range);
      setEditSeed(null);
      if (range == null) {
        setCommentAnnotation(null);
        return;
      }
      const derivedSide = range.endSide ?? range.side;
      const side: AnnotationSide =
        derivedSide === "deletions" ? "deletions" : "additions";
      const startLine = Math.min(range.start, range.end);
      const endLine = Math.max(range.start, range.end);

      setCommentAnnotation({
        side,
        lineNumber: endLine,
        metadata: { kind: "comment", startLine, endLine, side },
      });
    },
    [],
  );

  const openCommentForEdit = useCallback((seed: CommentEditSeed) => {
    setSelectedRange({
      start: seed.startLine,
      end: seed.endLine,
      side: seed.side,
      endSide: seed.side,
    });
    setCommentAnnotation({
      side: seed.side,
      lineNumber: seed.endLine,
      metadata: {
        kind: "comment",
        startLine: seed.startLine,
        endLine: seed.endLine,
        side: seed.side,
      },
    });
    setEditSeed(seed);
  }, []);

  return {
    selectedRange,
    commentAnnotation,
    hasOpenComment,
    editSeed,
    reset,
    handleLineSelectionChange,
    handleLineSelectionEnd,
    openCommentForEdit,
  };
}
