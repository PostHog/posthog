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
  sessionCostUsd?: number;
  onConfirm: () => Promise<boolean>;
  onCopyHandoffSummary?: () => Promise<void>;
  onCancel: () => void;
}

type ActiveAction = "copy_summary" | "switch" | null;

export function ModelSwitchCacheDialog({
  open,
  fromModelLabel,
  toModelId,
  toModelLabel,
  contextTokens = 0,
  sessionCostUsd,
  onConfirm,
  onCopyHandoffSummary,
  onCancel,
}: ModelSwitchCacheDialogProps): ReactElement {
  const setWarnOnModelSwitch = useSettingsStore(
    (state) => state.setWarnOnMidSessionModelSwitch,
  );
  const [dontShowAgain, setDontShowAgain] = useState(false);
  const [activeAction, setActiveAction] = useState<ActiveAction>(null);
  const checkboxId = useId();
  const cancelButtonRef = useRef<HTMLButtonElement>(null);
  const requestTokenRef = useRef(0);
  const estimatedInputCost = estimateUncachedInputCost(
    toModelId,
    contextTokens,
  );
  const hasCostInfo =
    estimatedInputCost !== null || sessionCostUsd !== undefined;
  const busy = activeAction !== null;

  useEffect(() => {
    if (open) {
      setDontShowAgain(false);
      setActiveAction(null);
      requestTokenRef.current += 1;
    }
  }, [open]);

  const rememberChoice = (): void => {
    if (dontShowAgain) setWarnOnModelSwitch(false);
  };

  const handleConfirm = async (): Promise<void> => {
    const token = requestTokenRef.current;
    setActiveAction("switch");
    try {
      if (await onConfirm()) rememberChoice();
    } finally {
      if (requestTokenRef.current === token) setActiveAction(null);
    }
  };

  const handleCopyHandoffSummary = async (): Promise<void> => {
    if (!onCopyHandoffSummary) return;
    const token = requestTokenRef.current;
    setActiveAction("copy_summary");
    try {
      await onCopyHandoffSummary();
    } finally {
      if (requestTokenRef.current === token) setActiveAction(null);
    }
  };

  return (
    <AlertDialog
      open={open}
      onOpenChange={(next) => {
        if (!next && !busy) onCancel();
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
        <div className="flex flex-col gap-4 px-4 pb-4">
          {hasCostInfo && (
            <div className="overflow-hidden rounded-(--radius-3) border border-(--gray-4) bg-(--gray-2)">
              <div className="flex items-center justify-center gap-2.5 px-3 py-3">
                <span className="truncate rounded-(--radius-2) bg-(--gray-4) px-2 py-1 text-[12px] text-muted-foreground">
                  {fromModelLabel}
                </span>
                <ArrowRight
                  size={13}
                  className="shrink-0 text-muted-foreground"
                />
                <span className="truncate rounded-(--radius-2) bg-(--gray-4) px-2 py-1 font-medium text-[12px] text-foreground">
                  {toModelLabel}
                </span>
              </div>
              <div className="flex flex-col gap-2 border-(--gray-4) border-t px-3 py-3">
                {estimatedInputCost !== null && (
                  <div className="flex items-center justify-between gap-4">
                    <Text className="text-[12px] text-muted-foreground">
                      Estimated cost to resend history
                    </Text>
                    <Text className="shrink-0 font-medium text-[12px] text-foreground tabular-nums">
                      {formatCostUsd(estimatedInputCost)}
                    </Text>
                  </div>
                )}
                {sessionCostUsd !== undefined && (
                  <div className="flex items-center justify-between gap-4">
                    <Text className="text-[12px] text-muted-foreground">
                      Session cost so far
                    </Text>
                    <Text className="shrink-0 font-medium text-[12px] text-foreground tabular-nums">
                      {formatCostUsd(sessionCostUsd)}
                    </Text>
                  </div>
                )}
              </div>
            </div>
          )}
          {onCopyHandoffSummary && (
            <div className="flex items-center justify-between gap-4">
              <div className="flex min-w-0 flex-col">
                <Text className="font-medium text-[12px] text-foreground">
                  Continue with another agent
                </Text>
                <Text className="text-[12px] text-muted-foreground">
                  Copy the important context from this conversation.
                </Text>
              </div>
              <Button
                variant="outline"
                size="sm"
                loading={activeAction === "copy_summary"}
                disabled={busy}
                data-attr="model-switch-cache-dialog-copy-summary"
                onClick={handleCopyHandoffSummary}
              >
                Copy summary
              </Button>
            </div>
          )}
          <div className="flex flex-col gap-1 border-(--gray-4) border-t pt-3">
            <div className="flex items-center gap-2">
              <Checkbox
                id={checkboxId}
                checked={dontShowAgain}
                disabled={busy}
                onCheckedChange={(checked) =>
                  setDontShowAgain(checked === true)
                }
                data-attr="model-switch-cache-dialog-dont-show-again"
              />
              <Label
                htmlFor={checkboxId}
                className="cursor-pointer text-[13px] text-muted-foreground"
              >
                Do not show this ever again
              </Label>
            </div>
            <Text className="text-[12px] text-muted-foreground">
              You can always change your mind in Cost management settings.
            </Text>
          </div>
        </div>
        <AlertDialogFooter className="flex-row justify-end">
          <Button
            ref={cancelButtonRef}
            variant="outline"
            disabled={busy}
            onClick={onCancel}
          >
            Cancel
          </Button>
          <Button
            variant="primary"
            loading={activeAction === "switch"}
            disabled={busy}
            data-attr="model-switch-cache-dialog-confirm"
            onClick={handleConfirm}
          >
            Switch now
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
