import { ChatCircle, Plus } from "@phosphor-icons/react";
import type { UserBasic } from "@posthog/shared/domain-types";
import type { EditorSelection } from "@posthog/ui/features/code-editor/components/CodeMirrorEditor";
import { CommentAnnotation } from "@posthog/ui/features/code-review/components/CommentAnnotation";
import { CommentComposer } from "@posthog/ui/features/sessions/components/CommentComposer";
import { SelectionCommentActionButton } from "@posthog/ui/features/sessions/components/SelectionCommentActionButton";
import { computeCommentActionPlacement } from "@posthog/ui/features/sessions/components/selectionCommentAction";
import { Tooltip } from "@posthog/ui/primitives/Tooltip";
import { useCallback, useEffect, useState } from "react";
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
  onSubmit: (
    startLine: number,
    endLine: number,
    text: string,
    mentions?: number[],
  ) => void | Promise<void>;
  onDismiss: () => void;
  actionLabel?: string;
  placeholder?: string;
  showActionText?: boolean;
  initiallyExpanded?: boolean;
  members?: UserBasic[];
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
  actionLabel = "Add to chat",
  placeholder,
  showActionText = false,
  initiallyExpanded = false,
  members,
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
      actionLabel={actionLabel}
      placeholder={placeholder}
      showActionText={showActionText}
      initiallyExpanded={initiallyExpanded}
      members={members}
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
  actionLabel,
  placeholder,
  showActionText,
  initiallyExpanded,
  members,
}: {
  anchor: { top: number; endX: number; bottom: number };
  fromLine: number;
  toLine: number;
  filePath: string;
  onSubmit: (
    startLine: number,
    endLine: number,
    text: string,
    mentions?: number[],
  ) => void | Promise<void>;
  onDismiss: () => void;
  actionLabel: string;
  placeholder?: string;
  showActionText: boolean;
  initiallyExpanded: boolean;
  members?: UserBasic[];
}) {
  const [userExpanded, setUserExpanded] = useState(false);
  const expanded = initiallyExpanded || userExpanded;
  const [draft, setDraft] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const actionSize = expanded
    ? { width: Math.min(420, window.innerWidth * 0.8), height: 180 }
    : { width: showActionText ? 104 : 28, height: 28 };
  const style = computeCommentActionPlacement(
    { top: anchor.top, right: anchor.endX, bottom: anchor.bottom },
    { width: window.innerWidth, height: window.innerHeight },
    actionSize,
    expanded ? "below" : "center",
  );

  useEffect(() => {
    const dismissOutside = (event: PointerEvent) => {
      if (
        event.target instanceof Element &&
        event.target.closest("[data-selection-comment-overlay]")
      ) {
        return;
      }
      onDismiss();
    };
    document.addEventListener("pointerdown", dismissOutside, true);
    return () =>
      document.removeEventListener("pointerdown", dismissOutside, true);
  }, [onDismiss]);

  if (!expanded) {
    const action = (
      <SelectionCommentActionButton
        label={actionLabel}
        iconOnly={!showActionText}
        position={style}
        onClick={() => setUserExpanded(true)}
      >
        {showActionText ? (
          <>
            <ChatCircle size={13} weight="bold" />
            Comment
          </>
        ) : (
          <Plus size={13} weight="bold" />
        )}
      </SelectionCommentActionButton>
    );
    // The text button names itself; only the icon-only variant needs a label
    // on hover.
    return createPortal(
      showActionText ? (
        action
      ) : (
        <Tooltip content={actionLabel}>{action}</Tooltip>
      ),
      document.body,
    );
  }

  return createPortal(
    <div
      data-selection-comment-overlay=""
      className="fixed z-50 w-[420px] max-w-[80vw] rounded-md border border-gray-5 bg-gray-2 shadow-lg"
      style={style}
    >
      {members ? (
        <div className="p-2">
          <CommentComposer
            value={draft}
            onValueChange={setDraft}
            onSubmit={async (content, mentions) => {
              if (submitting) return;
              setSubmitting(true);
              try {
                await onSubmit(fromLine, toLine, content, mentions);
                onDismiss();
              } finally {
                setSubmitting(false);
              }
            }}
            onCancel={onDismiss}
            members={members}
            placeholder={placeholder ?? "Add a comment…"}
            rows={2}
            disabled={submitting}
            autoFocus
          />
        </div>
      ) : (
        <CommentAnnotation
          filePath={filePath}
          startLine={fromLine}
          endLine={toLine}
          onDismiss={onDismiss}
          onSubmitText={(text) => onSubmit(fromLine, toLine, text)}
        />
      )}
    </div>,
    document.body,
  );
}
