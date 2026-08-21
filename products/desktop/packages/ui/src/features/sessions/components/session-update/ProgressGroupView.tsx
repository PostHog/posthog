import { ListChecks } from "@phosphor-icons/react";
import { type Step, StepList } from "@posthog/ui/primitives/StepList";
import { Box } from "@radix-ui/themes";
import { useEffect, useState } from "react";
import { ToolRow } from "./ToolRow";

interface ProgressGroupViewProps {
  steps: Step[];
  /** True while at least one step in this group is `in_progress`. */
  isActive: boolean;
  /** True once the enclosing turn has finished. Drives the auto-collapse. */
  turnComplete?: boolean;
}

// Header label follows the stream: the currently in-flight step's label if
// any, otherwise the last step seen. No hardcoded fallbacks — the backend
// controls all wording, including present-tense during `in_progress`.
function resolveHeaderLabel(steps: Step[]): string | null {
  if (steps.length === 0) return null;
  const active = steps.find((s) => s.status === "in_progress");
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
    // Any reactivation clears the sticky user choice so a new round of work
    // starts expanded again.
    if (isActive) setUserToggledOpen(null);
  }, [isActive]);

  if (steps.length === 0) return null;

  const hasHeader = steps.length > 1;
  const isSettled = turnComplete && !isActive;

  // Single-step groups have no header, so their body must stay expanded — collapsing with
  // no header would leave nothing on screen.
  if (!hasHeader) {
    return (
      <Box className="my-1">
        <StepList steps={steps} />
      </Box>
    );
  }

  // Multi-step groups stay open while the turn is running, then honour the user
  // toggle once the turn completes (default: collapsed).
  const isOpen = !isSettled ? true : (userToggledOpen ?? false);
  const summaryLabel = resolveHeaderLabel(steps) ?? "";

  return (
    <ToolRow
      icon={ListChecks}
      isLoading={isActive}
      open={isOpen}
      onOpenChange={(next) => {
        // Only the user's choice (after the turn finishes) sticks; while running
        // the row is controlled open, so a stray toggle is ignored.
        if (isSettled) setUserToggledOpen(next);
      }}
      content={<StepList steps={steps} />}
    >
      {summaryLabel}
    </ToolRow>
  );
}
