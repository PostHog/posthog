import type { Message } from "@earendil-works/pi-ai";
import type { UsageStats } from "../run-agent";
import type { WorkflowPhaseMetadata } from "../tools/workflow-runtime";
import type { WorkflowAgentStatus } from "./workflow-render";

export interface AgentRunSnapshot {
  runId: string;
  agent: string;
  task: string;
  composedPrompt?: string;
  model?: string;
  startedAt: number;
  usage: UsageStats;
  messages: Message[];
  errorMessage?: string;
}

export interface WorkflowAgentRunSnapshot extends WorkflowAgentStatus {
  task: string;
  model?: string;
  usage?: UsageStats;
  messages?: Message[];
  errorMessage?: string;
}

export interface WorkflowRunSnapshot {
  workflowId: string;
  name?: string;
  startedAt: number;
  phases: string[];
  phaseMetadata?: Record<string, WorkflowPhaseMetadata>;
  currentPhase?: string;
  agents: WorkflowAgentRunSnapshot[];
  logs: string[];
  tokensSpent: number;
  artifacts?: Array<{ name: string; phase: string; producer: string }>;
}

type Listener = () => void;
type StatusItem =
  | { kind: "agents"; id: string }
  | { kind: "workflow"; id: string };

const agentRuns = new Map<string, AgentRunSnapshot>();
const workflows = new Map<string, WorkflowRunSnapshot>();
const listeners = new Set<Listener>();
let focusedRunId: string | null = null;
let focusedWorkflowId: string | null = null;

function notify(): void {
  for (const listener of listeners) {
    listener();
  }
}

export function subscribeToOrchestration(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function upsertAgentRun(snapshot: AgentRunSnapshot): void {
  agentRuns.set(snapshot.runId, snapshot);
  notify();
}

export function removeAgentRun(runId: string): void {
  if (!agentRuns.delete(runId)) {
    return;
  }
  // Focus points at the aggregate "agents" row, not an individual run, so it
  // clears when that row disappears — i.e. when the last run ends.
  if (agentRuns.size === 0) {
    focusedRunId = null;
  }
  notify();
}

export function listAgentRuns(): AgentRunSnapshot[] {
  return [...agentRuns.values()].sort((a, b) => a.startedAt - b.startedAt);
}

export function hasActiveAgentRuns(): boolean {
  return agentRuns.size > 0;
}

export function upsertWorkflow(snapshot: WorkflowRunSnapshot): void {
  workflows.set(snapshot.workflowId, snapshot);
  notify();
}

export function removeWorkflow(workflowId: string): void {
  if (!workflows.delete(workflowId)) {
    return;
  }
  if (focusedWorkflowId === workflowId) {
    focusedWorkflowId = null;
  }
  notify();
}

export function listWorkflows(): WorkflowRunSnapshot[] {
  return [...workflows.values()].sort((a, b) => a.startedAt - b.startedAt);
}

export function getWorkflow(
  workflowId: string,
): WorkflowRunSnapshot | undefined {
  return workflows.get(workflowId);
}

export function hasActiveWorkflows(): boolean {
  return workflows.size > 0;
}

function emptyUsageTotal(): UsageStats {
  return {
    input: 0,
    output: 0,
    cacheRead: 0,
    cacheWrite: 0,
    cost: 0,
    contextTokens: 0,
    turns: 0,
  };
}

export function getCumulativeUsage(): UsageStats {
  const total = emptyUsageTotal();
  for (const run of agentRuns.values()) {
    total.input += run.usage.input;
    total.output += run.usage.output;
    total.cacheRead += run.usage.cacheRead;
    total.cacheWrite += run.usage.cacheWrite;
    total.cost += run.usage.cost;
    total.turns += run.usage.turns;
  }
  return total;
}

export function isFocused(): boolean {
  return focusedRunId !== null || focusedWorkflowId !== null;
}

export function getFocusedWorkflowId(): string | undefined {
  return focusedWorkflowId ?? undefined;
}

export function getFocusedRun(): AgentRunSnapshot | undefined {
  return focusedRunId ? agentRuns.get(focusedRunId) : undefined;
}

function statusItems(): StatusItem[] {
  const items: StatusItem[] = [];
  if (agentRuns.size > 0) {
    items.push({ kind: "agents", id: "agents" });
  }
  for (const workflow of listWorkflows()) {
    items.push({ kind: "workflow", id: workflow.workflowId });
  }
  return items;
}

export function focusFromEditor(): boolean {
  const [first] = statusItems();
  if (!first) {
    return false;
  }
  focusedRunId = first.kind === "agents" ? first.id : null;
  focusedWorkflowId = first.kind === "workflow" ? first.id : null;
  notify();
  return true;
}

export function moveDown(): void {
  const items = statusItems();
  if (items.length === 0) {
    blur();
    return;
  }
  const current = focusedRunId ? "agents" : focusedWorkflowId;
  const index = items.findIndex((item) => item.id === current);
  const next = items[Math.min(index + 1, items.length - 1)];
  focusedRunId = next.kind === "agents" ? next.id : null;
  focusedWorkflowId = next.kind === "workflow" ? next.id : null;
  notify();
}

export function moveUp(): void {
  const items = statusItems();
  if (items.length === 0) {
    blur();
    return;
  }
  const current = focusedRunId ? "agents" : focusedWorkflowId;
  const index = items.findIndex((item) => item.id === current);
  if (index <= 0) {
    blur();
    return;
  }
  const previous = items[index - 1];
  focusedRunId = previous.kind === "agents" ? previous.id : null;
  focusedWorkflowId = previous.kind === "workflow" ? previous.id : null;
  notify();
}

export function blur(): void {
  if (focusedRunId === null && focusedWorkflowId === null) {
    return;
  }
  focusedRunId = null;
  focusedWorkflowId = null;
  notify();
}

export function __resetOrchestrationForTesting(): void {
  agentRuns.clear();
  workflows.clear();
  listeners.clear();
  focusedRunId = null;
  focusedWorkflowId = null;
}
