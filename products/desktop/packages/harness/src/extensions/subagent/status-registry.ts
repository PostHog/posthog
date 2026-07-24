/**
 * In-memory registry of currently-active subagent runs, backing the footer
 * status indicator + overlay. Populated from `run-agent.ts#runAgent`.
 */

import type { Message } from "@earendil-works/pi-ai";
import { listWorkflows } from "../workflow/status-registry";
import type { UsageStats } from "./run-agent";

export interface AgentRunSnapshot {
  runId: string;
  agent: string;
  task: string;
  composedPrompt?: string;
  model?: string;
  startedAt: number;
  usage: UsageStats;
  /** Completed assistant messages received so far, for live overlay output. */
  messages: Message[];
  errorMessage?: string;
}

type Listener = () => void;

const runs = new Map<string, AgentRunSnapshot>();
const listeners = new Set<Listener>();
let focusedRunId: string | null = null;
let focusedWorkflowId: string | null = null;

function notify(): void {
  for (const listener of listeners) listener();
}

export function subscribeToAgentRuns(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function upsertAgentRun(snapshot: AgentRunSnapshot): void {
  runs.set(snapshot.runId, snapshot);
  notify();
}

export function removeAgentRun(runId: string): void {
  if (!runs.has(runId)) return;
  runs.delete(runId);
  if (focusedRunId === runId) focusedRunId = null;
  notify();
}

export function listAgentRuns(): AgentRunSnapshot[] {
  return [...runs.values()].sort((a, b) => a.startedAt - b.startedAt);
}

export function hasActiveAgentRuns(): boolean {
  return runs.size > 0;
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
  for (const run of runs.values()) {
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
  return focusedRunId ? runs.get(focusedRunId) : undefined;
}

export function focusFromEditor(): boolean {
  const [first] = statusItems();
  if (!first) return false;
  focusedRunId = first.kind === "agents" ? first.id : null;
  focusedWorkflowId = first.kind === "workflow" ? first.id : null;
  notify();
  return true;
}

type StatusItem =
  | { kind: "agents"; id: string }
  | { kind: "workflow"; id: string };

function statusItems(): StatusItem[] {
  const items: StatusItem[] = [];
  if (runs.size > 0) items.push({ kind: "agents", id: "agents" });
  for (const workflow of listWorkflows())
    items.push({ kind: "workflow", id: workflow.workflowId });
  return items;
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
  if (focusedRunId === null && focusedWorkflowId === null) return;
  focusedRunId = null;
  focusedWorkflowId = null;
  notify();
}

/** Test-only. */
export function __resetAgentRunsForTesting(): void {
  runs.clear();
  listeners.clear();
  focusedRunId = null;
  focusedWorkflowId = null;
}
