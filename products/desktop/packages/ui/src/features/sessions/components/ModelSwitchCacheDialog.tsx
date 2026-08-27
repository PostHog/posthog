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
import {
  formatCostUsd,
  formatTokensCompact,
} from "@posthog/ui/features/sessions/contextColors";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { type ReactElement, useEffect, useId, useState } from "react";

interface ModelSwitchCacheDialogProps {
  open: boolean;
  fromModelId: string;
  fromModelLabel: string;
  toModelId: string;
  toModelLabel: string;
  contextTokens?: number;
  sessionCostUsd?: number;
  onConfirm: () => Promise<void>;
  onCompactAndConfirm?: () => Promise<boolean>;
  onCopyHandoffSummary?: () => Promise<void>;
  onCancel: () => void;
}

type ActiveAction = "compact" | "copy_summary" | "switch" | null;

export function ModelSwitchCacheDialog({
  open,
  fromModelId,
  fromModelLabel,
  toModelId,
  toModelLabel,
  contextTokens = 0,
  sessionCostUsd,
  onConfirm,
  onCompactAndConfirm,
  onCopyHandoffSummary,
  onCancel,
}: ModelSwitchCacheDialogProps): ReactElement {
  const setWarnOnModelSwitch = useSettingsStore(
    (state) => state.setWarnOnMidSessionModelSwitch,
  );
  const [dontShowAgain, setDontShowAgain] = useState(false);
  const [activeAction, setActiveAction] = useState<ActiveAction>(null);
  const checkboxId = useId();
  const estimatedInputCost = estimateUncachedInputCost(
    toModelId,
    contextTokens,
  );
  const busy = activeAction !== null;

  useEffect(() => {
    if (open) setDontShowAgain(false);
  }, [open]);

  const rememberChoice = (): void => {
    if (dontShowAgain) setWarnOnModelSwitch(false);
  };

  const handleConfirm = async (): Promise<void> => {
    setActiveAction("switch");
    try {
      await onConfirm();
      rememberChoice();
    } finally {
      setActiveAction(null);
    }
  };

  const handleCompactAndConfirm = async (): Promise<void> => {
    if (!onCompactAndConfirm) return;
    setActiveAction("compact");
    try {
      if (await onCompactAndConfirm()) rememberChoice();
    } finally {
      setActiveAction(null);
    }
  };

  const handleCopyHandoffSummary = async (): Promise<void> => {
    if (!onCopyHandoffSummary) return;
    setActiveAction("copy_summary");
    try {
      await onCopyHandoffSummary();
    } finally {
      setActiveAction(null);
    }
  };

  return (
    <AlertDialog
      open={open}
      onOpenChange={(next) => {
        if (!next && !busy) onCancel();
      }}
    >
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Switch model mid-session?</AlertDialogTitle>
          <AlertDialogDescription>
            Cached context does not carry between models. Switch now, or compact
            the conversation first to reduce the context the new model must
            process.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <div className="flex flex-col gap-3 px-4 pb-4">
          <div className="flex flex-col gap-2 rounded-(--radius-3) border border-(--gray-4) bg-(--gray-2) px-4 py-3">
            <div className="flex items-center justify-center gap-2.5">
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
            {contextTokens > 0 && (
              <Text className="text-center text-[12px] text-muted-foreground">
                Switching now reprocesses about{" "}
                <span className="font-medium text-foreground tabular-nums">
                  {formatTokensCompact(contextTokens)} tokens
                </span>
                {estimatedInputCost !== null && (
                  <>
                    {" "}
                    for an estimated input cost of{" "}
                    <span className="font-medium text-foreground tabular-nums">
                      {formatCostUsd(estimatedInputCost)}
                    </span>
                  </>
                )}
                .
              </Text>
            )}
            {sessionCostUsd !== undefined && (
              <Text className="text-center text-[12px] text-muted-foreground">
                Estimated session cost so far:{" "}
                <span className="font-medium text-foreground tabular-nums">
                  {formatCostUsd(sessionCostUsd)}
                </span>
              </Text>
            )}
          </div>
          {onCopyHandoffSummary && (
            <Button
              variant="link-muted"
              size="sm"
              loading={activeAction === "copy_summary"}
              disabled={busy}
              data-attr="model-switch-cache-dialog-copy-summary"
              onClick={handleCopyHandoffSummary}
            >
              Copy a handoff summary
            </Button>
          )}
          <div className="flex items-center gap-2 py-1">
            <Checkbox
              id={checkboxId}
              checked={dontShowAgain}
              disabled={busy}
              onCheckedChange={(checked) => setDontShowAgain(checked === true)}
              data-attr="model-switch-cache-dialog-dont-show-again"
            />
            <Label
              htmlFor={checkboxId}
              className="cursor-pointer text-[13px] text-muted-foreground"
            >
              Do not show this again
            </Label>
          </div>
        </div>
        <AlertDialogFooter>
          <Button variant="outline" disabled={busy} onClick={onCancel}>
            Cancel
          </Button>
          <Button
            variant="outline"
            loading={activeAction === "switch"}
            disabled={busy}
            data-attr="model-switch-cache-dialog-confirm"
            onClick={handleConfirm}
          >
            Switch now
          </Button>
          {onCompactAndConfirm && (
            <Button
              variant="primary"
              loading={activeAction === "compact"}
              disabled={busy}
              data-attr="model-switch-cache-dialog-compact-confirm"
              onClick={handleCompactAndConfirm}
            >
              Compact and switch
            </Button>
          )}
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
