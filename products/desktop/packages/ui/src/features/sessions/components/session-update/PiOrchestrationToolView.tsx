import { ListChecks, Robot } from "@phosphor-icons/react";
import { Text } from "@posthog/quill";
import type { ToolCall } from "@posthog/ui/features/sessions/types";
import { type Step, StepList } from "@posthog/ui/primitives/StepList";
import { type ReactElement, useEffect, useState } from "react";
import {
  compactOrchestrationText,
  type PiOrchestrationAgentRunViewModel,
  type PiOrchestrationViewModel,
  summarizePiOrchestration,
} from "./piOrchestrationDetails";
import { ToolCallBlock } from "./ToolCallBlock";
import { ToolRow } from "./ToolRow";
import type { ToolViewProps } from "./toolCallUtils";
import { useToolCallStatus } from "./toolCallUtils";

interface PiOrchestrationToolViewProps extends ToolViewProps {
  view: PiOrchestrationViewModel;
}

function nestedToolCall(
  toolCall: PiOrchestrationAgentRunViewModel["toolCalls"][number],
): ToolCall {
  return { ...toolCall, toolCallId: toolCall.id };
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
  const [userToggledOpen, setUserToggledOpen] = useState(false);
  const noAgentsRan = view.agentRuns.length === 0 && !isLoading;
  const failureSummary =
    !view.cancelled && (isFailed || noAgentsRan)
      ? readFailureSummary(toolCall)
      : undefined;
  const summary =
    failureSummary ?? summarizePiOrchestration(view, { isLoading, isComplete });
  const isEffectivelyFailed =
    !view.cancelled && (isFailed || failureSummary !== undefined);

  useEffect(() => {
    if (isLoading) {
      setUserToggledOpen(false);
    }
  }, [isLoading]);

  let emptyStatus: Step["status"] = "completed";
  if (view.cancelled) {
    emptyStatus = "pending";
  } else if (isEffectivelyFailed) {
    emptyStatus = "failed";
  } else if (isLoading) {
    emptyStatus = "in_progress";
  }
  const isOpen = isLoading || userToggledOpen;
  const icon = view.kind === "workflow" ? ListChecks : Robot;
  let content: ReactElement;

  if (view.agentRuns.length > 0) {
    content = (
      <div className="flex flex-col gap-2">
        {view.agentRuns.map((run) => {
          const toolCalls = run.toolCalls.map(nestedToolCall);
          return (
            <ToolRow
              key={run.key}
              icon={Robot}
              isLoading={run.status === "in_progress"}
              isFailed={run.status === "failed"}
              content={
                toolCalls.length > 0 ? (
                  <div className="flex flex-col gap-1">
                    {toolCalls.map((toolCall) => (
                      <ToolCallBlock
                        key={toolCall.toolCallId}
                        toolCall={toolCall}
                        turnComplete={toolCall.status !== "in_progress"}
                      />
                    ))}
                  </div>
                ) : (
                  <Text className="text-gray-10 text-sm">
                    {run.errorMessage ?? "No tool calls yet"}
                  </Text>
                )
              }
            >
              <span className="flex min-w-0 items-center gap-1">
                <Text className="shrink-0 font-medium text-gray-12 text-sm">
                  {run.agent}
                </Text>
                <Text className="min-w-0 flex-1 truncate text-gray-10 text-sm">
                  · {run.description}
                </Text>
              </span>
            </ToolRow>
          );
        })}
      </div>
    );
  } else {
    content = (
      <StepList
        steps={[{ key: "summary", label: summary, status: emptyStatus }]}
        size="1"
        gap="3"
      />
    );
  }

  return (
    <ToolRow
      icon={icon}
      isLoading={isLoading}
      isFailed={isEffectivelyFailed}
      wasCancelled={wasCancelled}
      open={isOpen}
      onOpenChange={setUserToggledOpen}
      content={content}
    >
      <Text className="font-medium text-gray-12 text-sm">{summary}</Text>
    </ToolRow>
  );
}
