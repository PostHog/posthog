import { WarningIcon } from "@phosphor-icons/react";
import {
  Button,
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Field,
  FieldLabel,
  Input,
} from "@posthog/quill";
import {
  type CanvasV2Fragment,
  type CanvasV2FragmentPatch,
  type CanvasV2Op,
  checkFragmentCode,
} from "@posthog/shared";
import {
  DIALOG_CANCEL,
  EDIT_FRAGMENT_DIALOG_DESCRIPTION,
  EDIT_FRAGMENT_DIALOG_TITLE,
  EDIT_FRAGMENT_SUBMIT,
  FRAGMENT_CODE_BLOCKED_HINT,
  FRAGMENT_CODE_BLOCKED_TITLE,
  FRAGMENT_CODE_LABEL,
  FRAGMENT_TITLE_LABEL,
  FRAGMENT_TITLE_PLACEHOLDER,
  fragmentCodeBlockedReason,
} from "@posthog/ui/features/canvas-v2/canvasV2Copy";
import { SkillCodeEditor } from "@posthog/ui/features/skills/SkillCodeEditor";
import { type ReactElement, useEffect, useRef, useState } from "react";

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
  // The editor is uncontrolled after mount, so its document must stay stable.
  const [initialCode, setInitialCode] = useState("");
  const editingId = useRef<string | null>(null);

  useEffect(() => {
    if (!open || !fragment) {
      editingId.current = null;
      return;
    }
    if (editingId.current === fragment.id) return;
    editingId.current = fragment.id;
    setTitle(fragment.title ?? "");
    setCode(fragment.code);
    setInitialCode(fragment.code);
  }, [open, fragment]);

  const trimmedCode = code.trim();
  const blocked =
    trimmedCode.length > 0 ? checkFragmentCode(trimmedCode).violations : [];
  const canSubmit =
    Boolean(fragment) &&
    trimmedCode.length > 0 &&
    blocked.length === 0 &&
    !isPending;

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
        <DialogBody className="flex min-h-0 flex-col gap-5 pt-1">
          <Field className="gap-1.5">
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
          <Field className="gap-1.5">
            <FieldLabel>{FRAGMENT_CODE_LABEL}</FieldLabel>
            <div className="h-[min(52vh,440px)] overflow-hidden rounded-md border border-(--gray-6)">
              <SkillCodeEditor
                key={fragment?.id ?? "none"}
                initialContent={initialCode}
                filePath="fragment.tsx"
                onDocChanged={setCode}
              />
            </div>
            {blocked.length > 0 ? (
              <div className="flex items-start gap-2 rounded-md border border-(--red-6) bg-(--red-2) px-3 py-2">
                <WarningIcon
                  weight="fill"
                  className="mt-px size-3.5 shrink-0 text-(--red-9)"
                />
                <div className="min-w-0 space-y-0.5">
                  <p className="font-medium text-(--red-11) text-[12px]">
                    {FRAGMENT_CODE_BLOCKED_TITLE}
                  </p>
                  <p className="text-(--red-11)/85 text-[12px]">
                    {fragmentCodeBlockedReason(blocked)}
                  </p>
                  <p className="text-(--gray-11) text-[11px]">
                    {FRAGMENT_CODE_BLOCKED_HINT}
                  </p>
                </div>
              </div>
            ) : null}
          </Field>
        </DialogBody>
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
