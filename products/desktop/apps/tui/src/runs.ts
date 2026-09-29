import type { CloudTaskEngine } from "@posthog/core/cloud-task/cloud-task-engine";
import { CloudTaskEvent } from "@posthog/core/cloud-task/schemas";
import type {
  CloudTaskUpdatePayload,
  StoredLogEntry,
  TaskRunStatus,
} from "@posthog/shared";

export interface RunView {
  loaded: boolean;
  entries: StoredLogEntry[];
  status?: TaskRunStatus;
  sandboxAlive?: boolean | null;
  error: string | null;
}

export const emptyRunView: RunView = {
  loaded: false,
  entries: [],
  error: null,
};

export function applyUpdate(
  view: RunView,
  update: CloudTaskUpdatePayload,
): RunView {
  switch (update.kind) {
    case "snapshot":
      return {
        loaded: true,
        entries: update.newEntries,
        status: update.status ?? view.status,
        sandboxAlive: update.sandboxAlive ?? view.sandboxAlive,
        error: null,
      };
    case "logs":
      return { ...view, entries: [...view.entries, ...update.newEntries] };
    case "status":
      return {
        ...view,
        status: update.status ?? view.status,
        sandboxAlive: update.sandboxAlive ?? view.sandboxAlive,
      };
    case "error":
      return { ...view, error: `${update.errorTitle}: ${update.errorMessage}` };
    default:
      return view;
  }
}

// Watches cloud runs through one shared engine and hands each subscriber only its own run.
export class CloudRuns {
  constructor(
    private readonly engine: CloudTaskEngine,
    private readonly context: () => Promise<{
      apiHost: string;
      teamId: number;
    }>,
  ) {}

  watch(
    taskId: string,
    runId: string,
    onView: (view: RunView) => void,
  ): () => void {
    let view = emptyRunView;
    let stopped = false;
    const listener = (update: CloudTaskUpdatePayload): void => {
      if (update.taskId !== taskId || update.runId !== runId) return;
      view = applyUpdate(view, update);
      onView(view);
    };
    this.engine.on(CloudTaskEvent.Update, listener);
    this.context().then(
      ({ apiHost, teamId }) => {
        if (!stopped) this.engine.watch({ taskId, runId, apiHost, teamId });
      },
      (error: unknown) => {
        view = {
          ...view,
          error: error instanceof Error ? error.message : String(error),
        };
        onView(view);
      },
    );
    return () => {
      stopped = true;
      this.engine.off(CloudTaskEvent.Update, listener);
      this.engine.unwatch(taskId, runId);
    };
  }
}
