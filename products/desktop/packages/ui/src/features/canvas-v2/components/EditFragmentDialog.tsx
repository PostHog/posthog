import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Field,
  FieldLabel,
  Input,
  Textarea,
} from "@posthog/quill";
import type {
  CanvasV2Fragment,
  CanvasV2FragmentPatch,
  CanvasV2Op,
} from "@posthog/shared";
import {
  DIALOG_CANCEL,
  EDIT_FRAGMENT_DIALOG_DESCRIPTION,
  EDIT_FRAGMENT_DIALOG_TITLE,
  EDIT_FRAGMENT_SUBMIT,
  FRAGMENT_CODE_LABEL,
  FRAGMENT_TITLE_LABEL,
  FRAGMENT_TITLE_PLACEHOLDER,
} from "@posthog/ui/features/canvas-v2/canvasV2Copy";
import { type ReactElement, useEffect, useState } from "react";

interface EditFragmentDialogProps {
  open: boolean;
  /** The fragment being edited, or null while the dialog is closed. */
  fragment: CanvasV2Fragment | null;
  /** True while the parent still has the save in flight. */
  isPending: boolean;
  onOpenChange: (open: boolean) => void;
  applyLocal: (ops: CanvasV2Op[]) => void;
}

export function EditFragmentDialog({
  open,
  fragment,
  isPending,
  onOpenChange,
  applyLocal,
}: EditFragmentDialogProps): ReactElement {
  const [title, setTitle] = useState("");
  const [code, setCode] = useState("");

  useEffect(() => {
    if (!open || !fragment) return;
    setTitle(fragment.title ?? "");
    setCode(fragment.code);
  }, [open, fragment]);

  const trimmedCode = code.trim();
  const canSubmit = Boolean(fragment) && trimmedCode.length > 0 && !isPending;

  const submit = (): void => {
    if (!fragment || !canSubmit) return;
    const patch: CanvasV2FragmentPatch = { code };
    const trimmedTitle = title.trim();
    if (trimmedTitle !== (fragment.title ?? "")) {
      patch.title = trimmedTitle;
    }
    applyLocal([{ type: "update_fragment", id: fragment.id, patch }]);
    onOpenChange(false);
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next && isPending) return;
        onOpenChange(next);
      }}
    >
      <DialogContent size="wide">
        <DialogHeader>
          <DialogTitle>{EDIT_FRAGMENT_DIALOG_TITLE}</DialogTitle>
          <DialogDescription>
            {EDIT_FRAGMENT_DIALOG_DESCRIPTION}
          </DialogDescription>
        </DialogHeader>
        <Field>
          <FieldLabel htmlFor="canvas-v2-fragment-title">
            {FRAGMENT_TITLE_LABEL}
          </FieldLabel>
          <Input
            id="canvas-v2-fragment-title"
            value={title}
            placeholder={FRAGMENT_TITLE_PLACEHOLDER}
            onChange={(event) => setTitle(event.target.value)}
          />
        </Field>
        <Field>
          <FieldLabel htmlFor="canvas-v2-fragment-code">
            {FRAGMENT_CODE_LABEL}
          </FieldLabel>
          <Textarea
            id="canvas-v2-fragment-code"
            className="h-96 font-mono text-xs"
            spellCheck={false}
            value={code}
            onChange={(event) => setCode(event.target.value)}
          />
        </Field>
        <DialogFooter>
          <Button
            variant="outline"
            disabled={isPending}
            onClick={() => onOpenChange(false)}
          >
            {DIALOG_CANCEL}
          </Button>
          <Button
            variant="primary"
            loading={isPending}
            disabled={!canSubmit}
            onClick={submit}
          >
            {EDIT_FRAGMENT_SUBMIT}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
