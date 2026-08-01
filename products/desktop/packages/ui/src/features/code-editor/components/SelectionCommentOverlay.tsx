import { Plus } from "@phosphor-icons/react";
import { Button } from "@posthog/quill";
import type { EditorSelection } from "@posthog/ui/features/code-editor/components/CodeMirrorEditor";
import { CommentAnnotation } from "@posthog/ui/features/code-review/components/CommentAnnotation";
import { Tooltip } from "@radix-ui/themes";
import { useCallback, useState } from "react";
import { createPortal } from "react-dom";

/** Selection state for the "select lines → add to chat" overlay. */
export function useSelectionComposer() {
  const [selection, setSelection] = useState<EditorSelection | null>(null);
  const [open, setOpen] = useState(false);
  const onSelectionChange = useCallback((next: EditorSelection) => {
    setSelection(next);
    setOpen(next.text.trim().length > 0);
  }, []);
  const close = useCallback(() => setOpen(false), []);
  return { selection, open, onSelectionChange, close };
}

interface SelectionCommentOverlayProps {
  selection: EditorSelection | null;
  open: boolean;
  filePath: string;
  onSubmit: (startLine: number, endLine: number, text: string) => void;
  onDismiss: () => void;
}

/**
 * Selecting lines shows an explicit "+" button (like the code-review gutter);
 * clicking it opens the `CommentAnnotation` composer. Shared by the new-task
 * preview and the in-task editor.
 */
export function SelectionCommentOverlay({
  selection,
  open,
  filePath,
  onSubmit,
  onDismiss,
}: SelectionCommentOverlayProps) {
  if (!open || !selection?.anchor) return null;
  // Key by the range so a fresh selection remounts the card back to the "+".
  return (
    <SelectionComposerCard
      key={`${selection.fromLine}:${selection.toLine}`}
      anchor={selection.anchor}
      fromLine={selection.fromLine}
      toLine={selection.toLine}
      filePath={filePath}
      onSubmit={onSubmit}
      onDismiss={onDismiss}
    />
  );
}

function SelectionComposerCard({
  anchor,
  fromLine,
  toLine,
  filePath,
  onSubmit,
  onDismiss,
}: {
  anchor: { top: number; left: number };
  fromLine: number;
  toLine: number;
  filePath: string;
  onSubmit: (startLine: number, endLine: number, text: string) => void;
  onDismiss: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const style = { top: anchor.top + 4, left: anchor.left };

  if (!expanded) {
    return createPortal(
      <Tooltip content="Add to chat">
        <Button
          type="button"
          variant="primary"
          size="icon-sm"
          aria-label="Add selection to chat"
          className="fixed z-50 shadow-sm"
          style={style}
          onClick={() => setExpanded(true)}
        >
          <Plus size={14} weight="bold" />
        </Button>
      </Tooltip>,
      document.body,
    );
  }

  return createPortal(
    <div
      className="fixed z-50 w-[420px] max-w-[80vw] rounded-md border border-gray-5 bg-gray-2 shadow-lg"
      style={style}
    >
      <CommentAnnotation
        filePath={filePath}
        startLine={fromLine}
        endLine={toLine}
        onDismiss={onDismiss}
        onSubmitText={(text) => onSubmit(fromLine, toLine, text)}
      />
    </div>,
    document.body,
  );
}
