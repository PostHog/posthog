/** In-memory state for active workflow runs, used by the shared runtime UX. */
import type { Message } from "@earendil-works/pi-ai";
import type { UsageStats } from "../subagent/run-agent";
import type { WorkflowAgentStatus } from "./render";
import type { WorkflowPhaseMetadata } from "./runtime";

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
  /** Compact provenance only; never artifact values. */
  artifacts?: Array<{ name: string; phase: string; producer: string }>;
}

type Listener = () => void;

interface WorkflowStatusRegistry {
  workflows: Map<string, WorkflowRunSnapshot>;
  listeners: Set<Listener>;
}

// `workflow` and `subagent` are separate tsup entrypoints with splitting
// disabled. Each bundle gets its own module scope, so ordinary module-level
// Maps are not shared between the workflow publisher and the footer reader.
// Keep this deliberately process-local registry on globalThis instead.
const REGISTRY_KEY = "__posthogWorkflowStatusRegistry";
const globals = globalThis as typeof globalThis & {
  [REGISTRY_KEY]?: WorkflowStatusRegistry;
};
if (!globals[REGISTRY_KEY]) {
  globals[REGISTRY_KEY] = {
    workflows: new Map<string, WorkflowRunSnapshot>(),
    listeners: new Set<Listener>(),
  };
}
const registry: WorkflowStatusRegistry = globals[REGISTRY_KEY];

function notify(): void {
  for (const listener of registry.listeners) listener();
}

export function subscribeToWorkflows(listener: Listener): () => void {
  registry.listeners.add(listener);
  return () => registry.listeners.delete(listener);
}

export function upsertWorkflow(snapshot: WorkflowRunSnapshot): void {
  registry.workflows.set(snapshot.workflowId, snapshot);
  notify();
}

export function removeWorkflow(workflowId: string): void {
  if (!registry.workflows.delete(workflowId)) return;
  notify();
}

export function listWorkflows(): WorkflowRunSnapshot[] {
  return [...registry.workflows.values()].sort(
    (a, b) => a.startedAt - b.startedAt,
  );
}

export function getWorkflow(
  workflowId: string,
): WorkflowRunSnapshot | undefined {
  return registry.workflows.get(workflowId);
}

export function hasActiveWorkflows(): boolean {
  return registry.workflows.size > 0;
}

/** Test-only. */
export function __resetWorkflowsForTesting(): void {
  registry.workflows.clear();
  registry.listeners.clear();
}
