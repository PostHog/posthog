import { ListChecks, Robot } from "@phosphor-icons/react";
import { type Step, StepList } from "@posthog/ui/primitives/StepList";
import { Text } from "@radix-ui/themes";
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

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function readString(value: unknown): string | undefined {
  return typeof value === "string" && value.length > 0 ? value : undefined;
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

function readWorkflowStatus(value: unknown): Step["status"] {
  if (value === "done") {
    return "completed";
  }
  if (value === "error") {
    return "failed";
  }
  return "in_progress";
}

function readSubagentStatus(result: Record<string, unknown>): Step["status"] {
  if (result.state === "running") {
    return "in_progress";
  }
  if (result.state === "completed") {
    return "completed";
  }
  if (result.state === "failed" || result.state === "aborted") {
    return "failed";
  }

  const exitCode = typeof result.exitCode === "number" ? result.exitCode : -1;
  if (exitCode === -1) {
    return "in_progress";
  }
  return exitCode === 0 ? "completed" : "failed";
}

function readWorkflowDetails(
  details: unknown,
): PiOrchestrationViewModel | undefined {
  if (!isRecord(details) || !Array.isArray(details.agents)) {
    return undefined;
  }

  const name = readString(details.name);
  const currentPhase = readString(details.currentPhase);
  const steps = details.agents.flatMap((agent, index): Step[] => {
    if (!isRecord(agent)) {
      return [];
    }

    const label = readString(agent.label);
    const role = readString(agent.agent);
    if (!label || !role) {
      return [];
    }

    const status = readWorkflowStatus(agent.status);
    const objective = readString(agent.objective);

    return [
      {
        key: String(agent.id ?? index),
        label,
        status,
        detail: [role, objective].filter(Boolean).join(" · "),
      },
    ];
  });

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
  if (!isRecord(details) || !Array.isArray(details.results)) {
    return undefined;
  }

  const steps = details.results.flatMap((result, index): Step[] => {
    if (!isRecord(result)) {
      return [];
    }

    const agent = readString(result.agent);
    if (!agent) {
      return [];
    }

    const status = readSubagentStatus(result);
    const firstTaskLine = readString(result.task)?.trim().split("\n")[0];
    const task = truncateTask(firstTaskLine);
    const model = readString(result.model);

    return [
      {
        key: readString(result.runId) ?? String(index),
        label: agent,
        status,
        detail: [model, task].filter(Boolean).join(" · "),
      },
    ];
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
