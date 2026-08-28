import {
  type PiSubagentToolDetails,
  type PiWorkflowToolDetails,
  piSubagentToolDetailsSchema,
  piWorkflowToolDetailsSchema,
} from "@posthog/shared";
import type { Step } from "@posthog/ui/primitives/StepList";

const TASK_PREVIEW_LENGTH = 160;
const SUMMARY_ITEM_LIMIT = 3;

export interface PiOrchestrationViewModel {
  kind: "subagent" | "workflow";
  title: string;
  summary?: string;
  steps: Step[];
  hasReportedWork: boolean;
}

export function compactOrchestrationText(
  text: string,
  maxLength = TASK_PREVIEW_LENGTH,
): string {
  const compacted = text.replace(/\s+/g, " ").trim();
  if (compacted.length <= maxLength) {
    return compacted;
  }
  return `${compacted.slice(0, maxLength - 1)}…`;
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

function summarizeItems(items: string[]): string | undefined {
  if (items.length === 0) {
    return undefined;
  }
  const visibleItems = items.slice(0, SUMMARY_ITEM_LIMIT);
  const hiddenCount = items.length - visibleItems.length;
  if (hiddenCount > 0) {
    visibleItems.push(`+${hiddenCount} more`);
  }
  return visibleItems.join("; ");
}

function formatWorkflowName(name: string): string {
  const readableName = name.replace(/[-_]+/g, " ").trim();
  return `${readableName.charAt(0).toUpperCase()}${readableName.slice(1)}`;
}

function workflowAction(
  agent: PiWorkflowToolDetails["agents"][number],
): string {
  const completedDetail = agent.resultPreview ?? agent.objective;
  const activeDetail = agent.objective ?? agent.produces;
  const detail = agent.status === "done" ? completedDetail : activeDetail;
  if (!detail) {
    return `${agent.label} (${agent.agent})`;
  }
  return `${agent.label}: ${compactOrchestrationText(detail, 80)}`;
}

function workflowSummary(details: PiWorkflowToolDetails): string {
  const activeAgents = details.agents.filter(
    (agent) => agent.status === "running",
  );
  if (activeAgents.length > 0) {
    return `Running: ${summarizeItems(activeAgents.map(workflowAction))}`;
  }

  if (details.agents.length > 0) {
    const actions = summarizeItems(details.agents.map(workflowAction));
    const failedCount = details.agents.filter(
      (agent) => agent.status === "error",
    ).length;
    if (details.done && failedCount > 0) {
      return `Completed with ${failedCount} failed: ${actions}`;
    }
    if (details.done) {
      return `Completed: ${actions}`;
    }
    if (details.currentPhase) {
      return `${details.currentPhase}: ${actions}`;
    }
    return actions ?? "Preparing workflow";
  }

  if (details.currentPhase) {
    return `Running ${details.currentPhase}`;
  }
  if (details.phases && details.phases.length > 0) {
    return `Plan: ${details.phases.join(" → ")}`;
  }
  return "Preparing workflow";
}

function readWorkflowDetails(
  details: unknown,
): PiOrchestrationViewModel | undefined {
  const parsed = piWorkflowToolDetailsSchema.safeParse(details);
  if (!parsed.success) {
    return undefined;
  }

  const { name, phases, currentPhase, agents } = parsed.data;
  const steps = agents.map((agent): Step => {
    const completedDetail =
      agent.resultPreview ?? agent.objective ?? agent.produces;
    const activeDetail = agent.objective ?? agent.produces;
    return {
      key: String(agent.id),
      label: agent.label,
      status: readWorkflowStatus(agent.status),
      detail: [
        agent.agent,
        agent.status === "done" ? completedDetail : activeDetail,
      ]
        .filter(Boolean)
        .join(" · "),
    };
  });

  return {
    kind: "workflow",
    title: name ? `Workflow · ${formatWorkflowName(name)}` : "Workflow",
    summary: workflowSummary(parsed.data),
    steps,
    hasReportedWork: Boolean(
      currentPhase || agents.length > 0 || (phases && phases.length > 0),
    ),
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
  const summary = summarizeItems(
    parsed.data.results.map(
      (result) =>
        `${result.agent}: ${compactOrchestrationText(result.task, 80)}`,
    ),
  );

  return {
    kind: "subagent",
    title: steps.length > 1 ? "Subagents" : "Subagent",
    summary,
    steps,
    hasReportedWork: parsed.data.results.length > 0,
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
