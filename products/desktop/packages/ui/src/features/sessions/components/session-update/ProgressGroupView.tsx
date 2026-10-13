import { ListChecks } from "@phosphor-icons/react";
import { type Step, StepList } from "@posthog/ui/primitives/StepList";
import { useEffect, useState } from "react";
import { ToolRow } from "./ToolRow";

interface ProgressGroupViewProps {
  steps: Step[];
  isActive: boolean;
  turnComplete?: boolean;
}

function resolveHeaderLabel(steps: Step[]): string | null {
  if (steps.length === 0) return null;
  const active = steps.find((step) => step.status === "in_progress");
  if (active) return active.label;
  return steps[steps.length - 1].label;
}

export function ProgressGroupView({
  steps,
  isActive,
  turnComplete,
}: ProgressGroupViewProps) {
  const [userToggledOpen, setUserToggledOpen] = useState<boolean | null>(null);

  useEffect(() => {
    if (isActive) setUserToggledOpen(null);
  }, [isActive]);

  if (steps.length === 0) return null;

  const hasHeader = steps.length > 1;
  const isSettled = turnComplete && !isActive;

  if (!hasHeader) {
    return (
      <div className="my-1">
        <StepList steps={steps} />
      </div>
    );
  }

  const isOpen = !isSettled ? true : (userToggledOpen ?? false);
  const summaryLabel = resolveHeaderLabel(steps) ?? "";

  return (
    <ToolRow
      icon={ListChecks}
      isLoading={isActive}
      open={isOpen}
      onOpenChange={(next) => {
        if (isSettled) setUserToggledOpen(next);
      }}
      content={<StepList steps={steps} />}
    >
      {summaryLabel}
    </ToolRow>
  );
}
