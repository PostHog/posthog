import { ListChecks, Robot } from "@phosphor-icons/react";
import { Text } from "@posthog/quill";
import {
  type PiSubagentToolDetails,
  type PiWorkflowToolDetails,
  piSubagentToolDetailsSchema,
  piWorkflowToolDetailsSchema,
} from "@posthog/shared";
import { type Step, StepList } from "@posthog/ui/primitives/StepList";
import { type ReactElement, useEffect, useState } from "react";
import { ToolRow } from "./ToolRow";
import type { ToolViewProps } from "./toolCallUtils";
import { useToolCallStatus } from "./toolCallUtils";

const TASK_PREVIEW_LENGTH = 160;

interface PiOrchestrationViewModel {
  kind: "subagent" | "workflow";
  title: string;
  summary?: string;
  steps: Step[];
}

function truncateTask(task: string | undefined): string | undefined {
  if (!task) {
    return undefined;
  }
  if (task.length <= TASK_PREVIEW_LENGTH) {
    return task;
  }
  return `${task.slice(0, TASK_PREVIEW_LENGTH - 1)}…`;
}

function readWorkflowStatus(
  value: PiWorkflowToolDetails["agents"][number]["status"],
): Step["status"] {
  if (value === "done") {
    return "completed";
  }
  if (value === "error") {
    return "failed";
  }
  return "in_progress";
}

function readSubagentStatus(
  result: PiSubagentToolDetails["results"][number],
): Step["status"] {
  if (result.state === "running") {
    return "in_progress";
  }
  if (result.state === "completed") {
    return "completed";
  }
  if (result.state === "failed" || result.state === "aborted") {
    return "failed";
  }

  const exitCode = result.exitCode ?? -1;
  if (exitCode === -1) {
    return "in_progress";
  }
  return exitCode === 0 ? "completed" : "failed";
}

function readWorkflowDetails(
  details: unknown,
): PiOrchestrationViewModel | undefined {
  const parsed = piWorkflowToolDetailsSchema.safeParse(details);
  if (!parsed.success) {
    return undefined;
  }

  const { name, currentPhase, agents } = parsed.data;
  const steps = agents.map(
    (agent): Step => ({
      key: String(agent.id),
      label: agent.label,
      status: readWorkflowStatus(agent.status),
      detail: [agent.agent, agent.objective].filter(Boolean).join(" · "),
    }),
  );

  return {
    kind: "workflow",
    title: name ? `Workflow · ${name}` : "Workflow",
    summary: currentPhase,
    steps,
  };
}

function readSubagentDetails(
  details: unknown,
): PiOrchestrationViewModel | undefined {
  const parsed = piSubagentToolDetailsSchema.safeParse(details);
  if (!parsed.success) {
    return undefined;
  }

  const steps = parsed.data.results.map((result, index): Step => {
    const firstTaskLine = result.task.trim().split("\n")[0];
    const task = truncateTask(firstTaskLine);
    return {
      key: result.runId ?? String(index),
      label: result.agent,
      status: readSubagentStatus(result),
      detail: [result.model, task].filter(Boolean).join(" · "),
    };
  });

  return {
    kind: "subagent",
    title: steps.length > 1 ? "Subagents" : "Subagent",
    steps,
  };
}

export function readPiOrchestrationDetails(
  title: string | null | undefined,
  details: unknown,
): PiOrchestrationViewModel | undefined {
  if (title === "workflow") {
    return readWorkflowDetails(details);
  }
  if (title === "subagent") {
    return readSubagentDetails(details);
  }
  return undefined;
}

interface PiOrchestrationToolViewProps extends ToolViewProps {
  view: PiOrchestrationViewModel;
}

export function PiOrchestrationToolView({
  toolCall,
  turnCancelled,
  turnComplete,
  view,
}: PiOrchestrationToolViewProps): ReactElement {
  const { isLoading, isFailed, wasCancelled } = useToolCallStatus(
    toolCall.status,
    turnCancelled,
    turnComplete,
  );
  const [userToggledOpen, setUserToggledOpen] = useState<boolean | null>(null);

  useEffect(() => {
    if (isLoading) {
      setUserToggledOpen(null);
    }
  }, [isLoading]);

  let steps = view.steps;
  if (steps.length === 0 && view.summary) {
    let phaseStatus: Step["status"] = "completed";
    if (isFailed) {
      phaseStatus = "failed";
    } else if (isLoading) {
      phaseStatus = "in_progress";
    }
    steps = [{ key: "phase", label: view.summary, status: phaseStatus }];
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
        {view.summary && (
          <Text className="truncate text-gray-10 text-sm">
            · {view.summary}
          </Text>
        )}
      </span>
    </ToolRow>
  );
}
