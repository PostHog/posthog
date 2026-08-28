import { ListChecks, Robot } from "@phosphor-icons/react";
import { Text } from "@posthog/quill";
import { type Step, StepList } from "@posthog/ui/primitives/StepList";
import { type ReactElement, useEffect, useState } from "react";
import {
  compactOrchestrationText,
  type PiOrchestrationViewModel,
  summarizePiOrchestration,
} from "./piOrchestrationDetails";
import { ToolRow } from "./ToolRow";
import type { ToolViewProps } from "./toolCallUtils";
import { useToolCallStatus } from "./toolCallUtils";

interface PiOrchestrationToolViewProps extends ToolViewProps {
  view: PiOrchestrationViewModel;
}

function readFailureSummary(
  toolCall: ToolViewProps["toolCall"],
): string | undefined {
  for (const block of toolCall.content ?? []) {
    if (block.type === "content" && block.content.type === "text") {
      return compactOrchestrationText(block.content.text);
    }
  }
  return undefined;
}

export function PiOrchestrationToolView({
  toolCall,
  turnCancelled,
  turnComplete,
  view,
}: PiOrchestrationToolViewProps): ReactElement {
  const { isLoading, isFailed, wasCancelled, isComplete } = useToolCallStatus(
    toolCall.status,
    turnCancelled,
    turnComplete,
  );
  const [userToggledOpen, setUserToggledOpen] = useState<boolean | null>(null);
  let summary = summarizePiOrchestration(view, { isLoading, isComplete });
  if (isFailed) {
    summary = readFailureSummary(toolCall) ?? summary;
  }

  useEffect(() => {
    if (isLoading) {
      setUserToggledOpen(null);
    }
  }, [isLoading]);

  let steps = view.steps;
  if (steps.length === 0 && summary) {
    let phaseStatus: Step["status"] = "completed";
    if (isFailed) {
      phaseStatus = "failed";
    } else if (isLoading) {
      phaseStatus = "in_progress";
    }
    steps = [{ key: "phase", label: summary, status: phaseStatus }];
  }

  const isOpen = isLoading ? true : (userToggledOpen ?? false);
  const icon = view.kind === "workflow" ? ListChecks : Robot;

  return (
    <ToolRow
      icon={icon}
      isLoading={isLoading}
      isFailed={isFailed}
      wasCancelled={wasCancelled}
      open={isOpen}
      onOpenChange={setUserToggledOpen}
      content={
        steps.length > 0 ? <StepList steps={steps} size="1" /> : undefined
      }
    >
      <span className="flex min-w-0 items-center gap-1">
        <Text className="truncate font-medium text-gray-12 text-sm">
          {view.title}
        </Text>
        {summary && (
          <Text className="truncate text-gray-10 text-sm">· {summary}</Text>
        )}
      </span>
    </ToolRow>
  );
}
