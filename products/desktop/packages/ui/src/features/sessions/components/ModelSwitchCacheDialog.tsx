import { ArrowRight } from "@phosphor-icons/react";
import { estimateUncachedInputCost } from "@posthog/core/billing/modelPricing";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  Button,
  Checkbox,
  DialogBody,
  Label,
  Text,
} from "@posthog/quill";
import { formatCostUsd } from "@posthog/ui/features/sessions/contextColors";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { type ReactElement, useEffect, useId, useRef, useState } from "react";

interface ModelSwitchCacheDialogProps {
  open: boolean;
  fromModelLabel: string;
  toModelId: string;
  toModelLabel: string;
  contextTokens?: number;
  onConfirm: () => Promise<boolean>;
  onCancel: () => void;
}

export function ModelSwitchCacheDialog({
  open,
  ...props
}: ModelSwitchCacheDialogProps): ReactElement | null {
  if (!open) return null;

  return <OpenModelSwitchCacheDialog open {...props} />;
}

function OpenModelSwitchCacheDialog({
  open,
  fromModelLabel,
  toModelId,
  toModelLabel,
  contextTokens = 0,
  onConfirm,
  onCancel,
}: ModelSwitchCacheDialogProps): ReactElement {
  const setWarnOnModelSwitch = useSettingsStore(
    (state) => state.setWarnOnMidSessionModelSwitch,
  );
  const [dontShowAgain, setDontShowAgain] = useState(false);
  const [isSwitching, setIsSwitching] = useState(false);
  const checkboxId = useId();
  const cancelButtonRef = useRef<HTMLButtonElement>(null);
  const requestTokenRef = useRef(0);
  const estimatedInputCost = estimateUncachedInputCost(
    toModelId,
    contextTokens,
  );

  useEffect(() => {
    if (open) {
      setDontShowAgain(false);
      setIsSwitching(false);
      requestTokenRef.current += 1;
    }
  }, [open]);

  const handleConfirm = async (): Promise<void> => {
    const token = requestTokenRef.current;
    setIsSwitching(true);
    try {
      if (await onConfirm()) {
        if (dontShowAgain) setWarnOnModelSwitch(false);
      }
    } finally {
      if (requestTokenRef.current === token) setIsSwitching(false);
    }
  };

  return (
    <AlertDialog
      open={open}
      onOpenChange={(next) => {
        // Only the switch request holds the dialog, and it resolves in about a
        // second. Nothing else here can lock a person in.
        if (!next && !isSwitching) onCancel();
      }}
    >
      <AlertDialogContent initialFocus={cancelButtonRef}>
        <AlertDialogHeader>
          <AlertDialogTitle>Switch model mid-session?</AlertDialogTitle>
          <AlertDialogDescription>
            Cached context does not carry between models. Switching now resends
            the full conversation to the new model.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <DialogBody viewportClassName="flex flex-col gap-3.5 px-4 pb-4">
          <div className="flex flex-col gap-1.5">
            <div className="flex min-w-0 items-center gap-2 text-[13px]">
              <span className="truncate text-muted-foreground">
                {fromModelLabel}
              </span>
              <ArrowRight
                size={12}
                className="shrink-0 text-muted-foreground"
              />
              <span className="truncate font-medium text-foreground">
                {toModelLabel}
              </span>
            </div>
            {estimatedInputCost !== null && (
              <div className="flex items-baseline justify-between gap-4">
                <Text className="text-[13px] text-muted-foreground">
                  Estimated cost to resend history
                </Text>
                <Text className="shrink-0 font-medium text-[13px] text-foreground tabular-nums">
                  {formatCostUsd(estimatedInputCost)}
                </Text>
              </div>
            )}
          </div>
          <div className="flex flex-col gap-0.5 border-(--gray-4) border-t pt-3">
            <div className="flex items-center gap-2">
              <Checkbox
                id={checkboxId}
                checked={dontShowAgain}
                disabled={isSwitching}
                onCheckedChange={(checked) =>
                  setDontShowAgain(checked === true)
                }
                data-attr="model-switch-cache-dialog-dont-show-again"
              />
              <Label
                htmlFor={checkboxId}
                className="cursor-pointer text-[13px] text-muted-foreground"
              >
                Do not show this again
              </Label>
            </div>
            <Text className="pl-6 text-[11.5px] text-muted-foreground">
              Turn it back on in Cost management settings.
            </Text>
          </div>
        </DialogBody>
        <AlertDialogFooter className="flex-row justify-end">
          <Button
            ref={cancelButtonRef}
            variant="outline"
            disabled={isSwitching}
            onClick={onCancel}
          >
            Cancel
          </Button>
          <Button
            variant="primary"
            loading={isSwitching}
            disabled={isSwitching}
            data-attr="model-switch-cache-dialog-confirm"
            onClick={handleConfirm}
          >
            Switch model
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
