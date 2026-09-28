import type {
  AnnotationSide,
  DiffLineAnnotation,
  SelectedLineRange,
} from "@pierre/diffs";
import type { AnnotationMetadata } from "@posthog/ui/features/code-review/types";
import { useCallback } from "react";
import { create } from "zustand";

export interface CommentEditSeed {
  draftId: string;
  text: string;
  filePath: string;
  startLine: number;
  endLine: number;
  side: AnnotationSide;
}

interface CommentState {
  selectedRange: SelectedLineRange | null;
  commentAnnotation: DiffLineAnnotation<AnnotationMetadata> | null;
  editSeed: CommentEditSeed | null;
}

const emptyCommentState: CommentState = {
  selectedRange: null,
  commentAnnotation: null,
  editSeed: null,
};

const useOpenComments = create<{
  comments: Record<string, CommentState>;
  texts: Record<string, string>;
  update: (key: string, changes: Partial<CommentState>) => void;
  clear: (key: string) => void;
  setText: (key: string, text: string) => void;
}>()((set) => ({
  comments: {},
  texts: {},
  update: (key, changes) =>
    set((state) => ({
      comments: {
        ...state.comments,
        [key]: { ...(state.comments[key] ?? emptyCommentState), ...changes },
      },
    })),
  clear: (key) =>
    set((state) => {
      const comments = { ...state.comments };
      delete comments[key];
      const texts = { ...state.texts };
      delete texts[key];
      return { comments, texts };
    }),
  setText: (key, text) =>
    set((state) => ({ texts: { ...state.texts, [key]: text } })),
}));

export function useCommentText(taskId: string, filePath: string) {
  const key = JSON.stringify([taskId, filePath]);
  const text = useOpenComments((store) => store.texts[key]);
  const update = useOpenComments((store) => store.setText);
  const setText = useCallback(
    (value: string) => update(key, value),
    [key, update],
  );
  return { text, setText };
}

export function useCommentState(taskId: string | undefined, filePath: string) {
  const key = JSON.stringify([taskId, filePath]);
  const state = useOpenComments(
    (store) => store.comments[key] ?? emptyCommentState,
  );
  const update = useOpenComments((store) => store.update);
  const clear = useOpenComments((store) => store.clear);
  const updateText = useOpenComments((store) => store.setText);
  const { selectedRange, commentAnnotation, editSeed } = state;

  const hasOpenComment = commentAnnotation !== null;

  const reset = useCallback(() => {
    clear(key);
  }, [clear, key]);

  const handleLineSelectionChange = useCallback(
    (range: SelectedLineRange | null) => {
      update(key, { selectedRange: range });
    },
    [key, update],
  );

  const handleLineSelectionEnd = useCallback(
    (range: SelectedLineRange | null) => {
      if (range == null) {
        clear(key);
        return;
      }
      const derivedSide = range.endSide ?? range.side;
      const side: AnnotationSide =
        derivedSide === "deletions" ? "deletions" : "additions";
      const startLine = Math.min(range.start, range.end);
      const endLine = Math.max(range.start, range.end);

      updateText(key, "");
      update(key, {
        selectedRange: range,
        editSeed: null,
        commentAnnotation: {
          side,
          lineNumber: endLine,
          metadata: { kind: "comment", startLine, endLine, side },
        },
      });
    },
    [clear, key, update, updateText],
  );

  const openCommentForEdit = useCallback(
    (seed: CommentEditSeed) => {
      updateText(key, seed.text);
      update(key, {
        selectedRange: {
          start: seed.startLine,
          end: seed.endLine,
          side: seed.side,
          endSide: seed.side,
        },
        commentAnnotation: {
          side: seed.side,
          lineNumber: seed.endLine,
          metadata: {
            kind: "comment",
            startLine: seed.startLine,
            endLine: seed.endLine,
            side: seed.side,
          },
        },
        editSeed: seed,
      });
    },
    [key, update, updateText],
  );

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
