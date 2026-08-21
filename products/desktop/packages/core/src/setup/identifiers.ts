import type { ActivityEntry } from "@posthog/core/setup/setupState";
import type { StaleFlagPayload } from "@posthog/core/setup/suggestions";
import type { DiscoveredTask } from "@posthog/core/setup/types";

export type DiscoverySignalSource =
  | "structured_output"
  | "terminal_status"
  | "missing_output";

export type DiscoveryFailureReason =
  | "timeout"
  | "failed"
  | "cancelled"
  | "startup_error";

/**
 * Host capabilities the setup discovery/enrichment orchestration needs.
 *
 * The desktop adapter wraps trpc (agent/enrichment), the authenticated PostHog
 * API client (task runs), analytics, and build/env flags. The interface speaks
 * product intent so the orchestration stays host-agnostic: no trpc, no Electron,
 * no analytics taxonomy, no `import.meta.env` inside the package.
 */
export interface ISetupRunService {
  /** Auth/project context for a discovery run. `authed` is false when no authenticated client is available. */
  getDiscoveryContext(): Promise<{
    apiHost: string | null;
    projectId: number | null;
    authed: boolean;
  }>;
  createDiscoveryTask(input: {
    title: string;
    description: string;
    jsonSchema: Record<string, unknown>;
  }): Promise<{ id: string }>;
  createTaskRun(taskId: string): Promise<{ id: string | null }>;
  getTaskRun(
    taskId: string,
    taskRunId: string,
  ): Promise<{ status: string; tasks: DiscoveredTask[] | null }>;
  isTerminalStatus(status: string): boolean;

  startAgent(input: {
    taskId: string;
    taskRunId: string;
    repoPath: string;
    apiHost: string;
    projectId: number;
    jsonSchema: Record<string, unknown>;
  }): Promise<void>;
  sendPrompt(input: { sessionId: string; promptText: string }): Promise<void>;
  subscribeSessionEvents(
    input: { taskRunId: string },
    handlers: {
      onData: (payload: unknown) => void;
      onError: (err: unknown) => void;
    },
  ): { unsubscribe: () => void };

  detectPosthogInstallState(
    repoPath: string,
  ): Promise<"initialized" | "not_installed" | "installed_no_init">;
  findStaleFlagSuggestions(repoPath: string): Promise<StaleFlagPayload[]>;

  /** Whether experiment-tier suggestions are enabled (feature flag or dev build). */
  includeExperiments(): boolean;

  trackDiscoveryStarted(p: { taskId: string; taskRunId: string }): void;
  trackDiscoveryCompleted(p: {
    taskId: string;
    taskRunId: string;
    taskCount: number;
    durationSeconds: number;
    signalSource: DiscoverySignalSource;
  }): void;
  trackDiscoveryFailed(p: {
    taskId?: string;
    taskRunId?: string;
    reason: DiscoveryFailureReason;
    errorMessage?: string;
  }): void;
  reportError(error: Error, scope: string): void;
}

export const SETUP_RUN_SERVICE = Symbol.for("posthog.core.setupRunService");

/**
 * Host-supplied window onto the setup zustand store. Inverts the store
 * coupling so the core orchestration writes UI state through a narrow
 * interface instead of importing `@posthog/ui`. The apps composition binds
 * this to a delegate over `useSetupStore.getState()`.
 */
export interface ISetupStore {
  getDiscoveryStatus(repoPath: string): "idle" | "running" | "done" | "error";
  getEnricherStatus(repoPath: string): "idle" | "running" | "done" | "error";
  anyDiscoveryStarted(): boolean;

  startDiscovery(repoPath: string, taskId: string, taskRunId: string): void;
  completeDiscovery(repoPath: string, tasks: DiscoveredTask[]): void;
  failDiscovery(repoPath: string, message?: string): void;
  pushDiscoveryActivity(repoPath: string, entry: ActivityEntry): void;

  startEnrichment(repoPath: string): void;
  completeEnrichment(repoPath: string): void;
  failEnrichment(repoPath: string): void;
  addEnricherSuggestionIfMissing(task: DiscoveredTask): void;
}

export const SETUP_STORE = Symbol.for("posthog.core.setupStore");
