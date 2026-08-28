import {
  type PiSubagentToolDetails,
  type PiWorkflowToolDetails,
  piSubagentToolDetailsSchema,
  piWorkflowToolDetailsSchema,
} from "@posthog/shared";
import type { Step } from "@posthog/ui/primitives/StepList";

const TASK_PREVIEW_LENGTH = 160;

interface OrchestrationCounts {
  total: number;
  running: number;
  completed: number;
  failed: number;
}

export interface PiOrchestrationViewModel {
  kind: "subagent" | "workflow";
  title: string;
  phase?: string;
  plannedPhaseCount: number;
  counts: OrchestrationCounts;
  steps: Step[];
}

export interface PiOrchestrationDisplayState {
  isLoading: boolean;
  isComplete: boolean;
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

function formatWorkflowName(name: string): string {
  const readableName = name.replace(/[-_]+/g, " ").trim();
  return `${readableName.charAt(0).toUpperCase()}${readableName.slice(1)}`;
}

function countSteps(steps: Step[]): OrchestrationCounts {
  return {
    total: steps.length,
    running: steps.filter((step) => step.status === "in_progress").length,
    completed: steps.filter((step) => step.status === "completed").length,
    failed: steps.filter((step) => step.status === "failed").length,
  };
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
    phase: currentPhase,
    plannedPhaseCount: phases?.length ?? 0,
    counts: countSteps(steps),
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
  const singleAgent = parsed.data.results[0]?.agent;

  return {
    kind: "subagent",
    title:
      steps.length === 1 && singleAgent
        ? `Subagent · ${singleAgent}`
        : "Subagents",
    plannedPhaseCount: 0,
    counts: countSteps(steps),
    steps,
  };
}

function agentCount(count: number): string {
  return count === 1 ? "1 agent" : `${count} agents`;
}

function activeSummary(view: PiOrchestrationViewModel): string {
  const { running, completed } = view.counts;
  if (running > 1) {
    const completedSuffix = completed > 0 ? ` · ${completed} completed` : "";
    return `${running} agents running in parallel${completedSuffix}`;
  }
  if (running === 1) {
    const completedSuffix = completed > 0 ? ` · ${completed} completed` : "";
    return `1 agent running${completedSuffix}`;
  }
  if (view.phase) {
    return `Running ${view.phase}`;
  }
  if (view.plannedPhaseCount > 0) {
    return `Preparing ${view.plannedPhaseCount} phases`;
  }
  return "Preparing";
}

function completedSummary(view: PiOrchestrationViewModel): string {
  const { total, completed, failed } = view.counts;
  if (total === 0) {
    return view.phase ? `Reached ${view.phase}` : "No agents started";
  }
  if (failed === 0 && completed === total) {
    return `${agentCount(completed)} completed`;
  }

  const summaries: string[] = [];
  if (completed > 0) {
    summaries.push(`${completed} completed`);
  }
  if (failed > 0) {
    summaries.push(`${failed} failed`);
  }
  const notCompleted = total - completed - failed;
  if (notCompleted > 0) {
    summaries.push(`${notCompleted} not completed`);
  }
  return summaries.join(" · ");
}

function stoppedSummary(view: PiOrchestrationViewModel): string {
  const { total, completed, failed } = view.counts;
  if (total === 0) {
    return view.phase ? `Stopped in ${view.phase}` : "No agents started";
  }

  const stopped = total - completed - failed;
  const summaries: string[] = [];
  if (completed > 0) {
    summaries.push(`${completed} completed`);
  }
  if (failed > 0) {
    summaries.push(`${failed} failed`);
  }
  if (stopped > 0) {
    summaries.push(`${stopped} stopped`);
  }
  return summaries.join(" · ");
}

export function summarizePiOrchestration(
  view: PiOrchestrationViewModel,
  state: PiOrchestrationDisplayState,
): string {
  if (state.isLoading) {
    return activeSummary(view);
  }
  if (state.isComplete) {
    return completedSummary(view);
  }
  return stoppedSummary(view);
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
