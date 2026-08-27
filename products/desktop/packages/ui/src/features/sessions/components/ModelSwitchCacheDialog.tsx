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
import { type ReactElement, useEffect, useId, useRef, useState } from "react";

interface ModelSwitchCacheDialogProps {
  open: boolean;
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
  const cancelButtonRef = useRef<HTMLButtonElement>(null);
  // Identifies the current dialog request. The parent can close and reopen this
  // dialog for a different session without remounting it, so bump the token on
  // each open to scope activeAction to one request.
  const requestTokenRef = useRef(0);
  const estimatedInputCost = estimateUncachedInputCost(
    toModelId,
    contextTokens,
  );
  const busy = activeAction !== null;

  useEffect(() => {
    if (open) {
      setDontShowAgain(false);
      // A controlled close leaves activeAction set (the parent drops the pending
      // switch without remounting), so a reopened dialog would inherit the old
      // busy state and lock its controls. Reset on open and invalidate any
      // in-flight action so its finally cannot clear the new request's state.
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
      await onConfirm();
      rememberChoice();
    } finally {
      if (requestTokenRef.current === token) setActiveAction(null);
    }
  };

  const handleCompactAndConfirm = async (): Promise<void> => {
    if (!onCompactAndConfirm) return;
    const token = requestTokenRef.current;
    setActiveAction("compact");
    try {
      if (await onCompactAndConfirm()) rememberChoice();
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
            Cached context does not carry between models. Switch now, or compact
            the conversation first to reduce the context the new model must
            process.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <div className="flex flex-col gap-4 px-4 pb-4">
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
            {(contextTokens > 0 || sessionCostUsd !== undefined) && (
              <div className="flex flex-col gap-2 border-(--gray-4) border-t px-3 py-3">
                {contextTokens > 0 && (
                  <div className="flex items-center justify-between gap-4">
                    <Text className="text-[12px] text-muted-foreground">
                      Context to reprocess
                    </Text>
                    <Text className="shrink-0 font-medium text-[12px] text-foreground tabular-nums">
                      ~{formatTokensCompact(contextTokens)} tokens
                    </Text>
                  </div>
                )}
                {estimatedInputCost !== null && (
                  <div className="flex items-center justify-between gap-4">
                    <Text className="text-[12px] text-muted-foreground">
                      Estimated input cost
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
            )}
          </div>
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
          <div className="flex items-center gap-2 border-(--gray-4) border-t pt-3">
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
