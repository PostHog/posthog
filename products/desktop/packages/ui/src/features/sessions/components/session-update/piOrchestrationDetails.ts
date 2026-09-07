import {
  type PiSubagentToolCall,
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

export interface PiOrchestrationAgentRunViewModel {
  key: string;
  agent: string;
  description: string;
  status: Step["status"];
  toolCalls: PiSubagentToolCall[];
  errorMessage?: string;
}

export interface PiOrchestrationViewModel {
  kind: "subagent" | "workflow";
  workflowName?: string;
  counts: OrchestrationCounts;
  agentRuns: PiOrchestrationAgentRunViewModel[];
  cancelled: boolean;
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

function readWorkflowStatus(
  value: PiWorkflowToolDetails["agents"][number]["status"],
): Step["status"] {
  if (value === "done") {
    return "completed";
  }
  if (value === "error") {
    return "failed";
  }
  if (value === "aborted") {
    return "pending";
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

function countAgentRuns(
  agentRuns: PiOrchestrationAgentRunViewModel[],
): OrchestrationCounts {
  return {
    total: agentRuns.length,
    running: agentRuns.filter((run) => run.status === "in_progress").length,
    completed: agentRuns.filter((run) => run.status === "completed").length,
    failed: agentRuns.filter((run) => run.status === "failed").length,
  };
}

function readWorkflowDetails(
  details: unknown,
): PiOrchestrationViewModel | undefined {
  const parsed = piWorkflowToolDetailsSchema.safeParse(details);
  if (!parsed.success) {
    return undefined;
  }

  const { name, agents } = parsed.data;
  const agentRuns = agents.map(
    (agent): PiOrchestrationAgentRunViewModel => ({
      key: String(agent.id),
      agent: agent.label,
      description: agent.objective ?? agent.produces ?? agent.agent,
      status: readWorkflowStatus(agent.status),
      toolCalls: agent.toolCalls ?? [],
    }),
  );
  return {
    kind: "workflow",
    workflowName: name ? formatWorkflowName(name) : undefined,
    counts: countAgentRuns(agentRuns),
    agentRuns,
    cancelled: parsed.data.cancelled ?? false,
  };
}

function readSubagentDetails(
  details: unknown,
): PiOrchestrationViewModel | undefined {
  const parsed = piSubagentToolDetailsSchema.safeParse(details);
  if (!parsed.success) {
    return undefined;
  }

  const subagentRuns = parsed.data.results.map(
    (result, index): PiOrchestrationAgentRunViewModel => ({
      key: result.runId ?? String(index),
      agent: result.agent,
      description: result.description ?? result.task.trim().split("\n")[0],
      status: readSubagentStatus(result),
      toolCalls: result.toolCalls ?? [],
      errorMessage: result.errorMessage,
    }),
  );
  return {
    kind: "subagent",
    counts: countAgentRuns(subagentRuns),
    agentRuns: subagentRuns,
    cancelled: false,
  };
}

function subagentCount(count: number): string {
  return count === 1 ? "1 subagent" : `${count} subagents`;
}

function summarizeWorkflowRun(
  view: PiOrchestrationViewModel,
  state: PiOrchestrationDisplayState,
): string {
  const name = view.workflowName ? `: ${view.workflowName}` : "";
  if (state.isLoading) {
    return `Running workflow${name}`;
  }
  if (view.cancelled) {
    return `Ran workflow${name}, canceled`;
  }
  if (state.isComplete && view.counts.failed > 0) {
    return `Ran workflow${name}, ${view.counts.failed} failed`;
  }
  return `Ran workflow${name}`;
}

function summarizeSubagentRun(
  view: PiOrchestrationViewModel,
  state: PiOrchestrationDisplayState,
): string {
  const count = subagentCount(view.counts.total);
  if (state.isLoading) {
    return `Running ${count}`;
  }
  if (view.cancelled) {
    return `Ran ${count}, canceled`;
  }
  if (state.isComplete) {
    return view.counts.failed > 0
      ? `Ran ${count}, ${view.counts.failed} failed`
      : `Ran ${count}`;
  }
  return `Ran ${count}, ${formatStoppedCounts(view)}`;
}

function formatStoppedCounts(view: PiOrchestrationViewModel): string {
  const { total, completed, failed } = view.counts;
  if (total === 0) {
    return "";
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
  return view.kind === "workflow"
    ? summarizeWorkflowRun(view, state)
    : summarizeSubagentRun(view, state);
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
