import type { ChangeEvent, FocusEvent, KeyboardEvent } from "react";
import { useRef, useState } from "react";

type CommitOnEnter = "never" | "enter" | "enter-no-shift";

export type InlineEditOptions = {
  current: string;
  isPending: boolean;
  allowEmpty?: boolean;
  commitOnEnter?: CommitOnEnter;
  onCommit: (value: string, controls: { reset: () => void }) => void;
};

export type InlineEdit = {
  draft: string | null;
  isEditing: boolean;
  startEditing: () => void;
  reset: () => void;
  inputProps: {
    onChange: (
      event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>,
    ) => void;
    onBlur: (event: FocusEvent<HTMLInputElement | HTMLTextAreaElement>) => void;
    onKeyDown: (event: KeyboardEvent<HTMLElement>) => void;
  };
};

export function useInlineEdit({
  current,
  isPending,
  allowEmpty = false,
  commitOnEnter = "never",
  onCommit,
}: InlineEditOptions): InlineEdit {
  const [draft, setDraft] = useState<string | null>(null);
  const skipCommit = useRef(false);
  const reset = () => setDraft(null);

  const commit = (value: string) => {
    if (skipCommit.current) {
      skipCommit.current = false;
      return;
    }
    if (isPending) return;
    const trimmed = value.trim();
    if (!trimmed && !allowEmpty) {
      reset();
      return;
    }
    if (trimmed === current.trim()) {
      reset();
      return;
    }
    onCommit(trimmed, { reset });
  };

  const commitsOnEnter = (event: KeyboardEvent<HTMLElement>) => {
    if (commitOnEnter === "enter") return true;
    if (commitOnEnter === "enter-no-shift") return !event.shiftKey;
    return false;
  };

  return {
    draft,
    isEditing: draft !== null,
    startEditing: () => setDraft(current),
    reset,
    inputProps: {
      onChange: (event) => setDraft(event.currentTarget.value),
      onBlur: (event) => commit(event.currentTarget.value),
      onKeyDown: (event) => {
        if (event.key === "Escape") {
          skipCommit.current = true;
          setDraft(null);
          event.currentTarget.blur();
        } else if (event.key === "Enter" && commitsOnEnter(event)) {
          event.preventDefault();
          event.currentTarget.blur();
        }
      },
    },
  };
}
