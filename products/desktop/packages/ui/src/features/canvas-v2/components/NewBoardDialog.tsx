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
  BOARD_NAME_LABEL,
  BOARD_NAME_PLACEHOLDER,
  DEFAULT_BOARD_NAME,
  DIALOG_CANCEL,
  NEW_BOARD_DIALOG_DESCRIPTION,
  NEW_BOARD_DIALOG_TITLE,
  NEW_BOARD_SUBMIT,
  RENAME_BOARD_DIALOG_DESCRIPTION,
  RENAME_BOARD_DIALOG_TITLE,
  RENAME_BOARD_SUBMIT,
} from "@posthog/ui/features/canvas-v2/canvasV2Copy";
import { type ReactElement, useEffect, useState } from "react";

export type BoardNameDialogMode = "create" | "rename";

interface NewBoardDialogProps {
  open: boolean;
  mode?: BoardNameDialogMode;
  /** Name the field starts with. Used by the rename mode. */
  initialName?: string;
  isPending: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (name: string) => void;
}

const COPY: Record<
  BoardNameDialogMode,
  { title: string; description: string; submit: string }
> = {
  create: {
    title: NEW_BOARD_DIALOG_TITLE,
    description: NEW_BOARD_DIALOG_DESCRIPTION,
    submit: NEW_BOARD_SUBMIT,
  },
  rename: {
    title: RENAME_BOARD_DIALOG_TITLE,
    description: RENAME_BOARD_DIALOG_DESCRIPTION,
    submit: RENAME_BOARD_SUBMIT,
  },
};

/** One name field, used to create a board and to rename one. */
export function NewBoardDialog({
  open,
  mode = "create",
  initialName = "",
  isPending,
  onOpenChange,
  onSubmit,
}: NewBoardDialogProps): ReactElement {
  const [name, setName] = useState(initialName);
  const copy = COPY[mode];
  const trimmed = name.trim();
  const canSubmit = trimmed.length > 0 && !isPending;

  useEffect(() => {
    if (!open) return;
    setName(initialName || (mode === "create" ? DEFAULT_BOARD_NAME : ""));
  }, [open, initialName, mode]);

  const submit = () => {
    if (!canSubmit) return;
    onSubmit(trimmed);
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next && isPending) return;
        onOpenChange(next);
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{copy.title}</DialogTitle>
          <DialogDescription>{copy.description}</DialogDescription>
        </DialogHeader>
        <DialogBody>
          <Field className="gap-1.5">
            <FieldLabel htmlFor="canvas-v2-board-name">
              {BOARD_NAME_LABEL}
            </FieldLabel>
            <Input
              id="canvas-v2-board-name"
              autoFocus
              value={name}
              placeholder={BOARD_NAME_PLACEHOLDER}
              onFocus={(event) => event.currentTarget.select()}
              onChange={(event) => setName(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") submit();
              }}
            />
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
            {copy.submit}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
