import {
  claimHolderName,
  type ImplementationClaimStep,
} from "@posthog/core/inbox/reportActions";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  Button,
} from "@posthog/quill";
import type { ReactElement } from "react";

export type ImplementClaimDialogStep = Extract<
  ImplementationClaimStep,
  { kind: "take_over" | "confirm_own_agent" }
>;

interface ImplementClaimDialogProps {
  step: ImplementClaimDialogStep;
  isSubmitting: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

function dialogCopy(step: ImplementClaimDialogStep): {
  title: string;
  description: string;
  confirm: string;
} {
  if (step.kind === "confirm_own_agent") {
    return {
      title: "Start another run?",
      description:
        "Your agent is already working on this report. A PostHog run could open a second pull request.",
      confirm: "Start run",
    };
  }
  const name = claimHolderName(step.holder);
  return {
    title: "Take over this report?",
    description: `${step.viaAgent ? `${name}'s agent` : name} is working on this report. If you take it over, we let ${name} know.`,
    confirm: "Take over and implement",
  };
}

/** Asks before Create PR takes a teammate's claim, or starts a run while the user's own agent works on the report. */
export function ImplementClaimDialog({
  step,
  isSubmitting,
  onConfirm,
  onCancel,
}: ImplementClaimDialogProps): ReactElement {
  const copy = dialogCopy(step);
  return (
    <AlertDialog
      open
      onOpenChange={(next) => {
        if (!next && !isSubmitting) onCancel();
      }}
    >
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{copy.title}</AlertDialogTitle>
          <AlertDialogDescription>{copy.description}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <Button variant="outline" onClick={onCancel} disabled={isSubmitting}>
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={onConfirm}
            loading={isSubmitting}
            disabled={isSubmitting}
          >
            {copy.confirm}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
