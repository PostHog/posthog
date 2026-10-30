import type { TaskRunSessionLogsPage } from "@posthog/api-client/posthog-client";
import type { CloudTaskEngine } from "@posthog/core/cloud-task/cloud-task-engine";
import { CloudTaskEvent } from "@posthog/core/cloud-task/schemas";
import type {
  CloudTaskUpdatePayload,
  StoredLogEntry,
  TaskRunStatus,
} from "@posthog/shared";
import type { TranscriptLine } from "./transcript";

export interface RunView {
  loaded: boolean;
  entries: StoredLogEntry[];
  // Index in the run's full log of entries[0]; above zero, older entries can page in.
  windowStart: number;
  loadingOlder: boolean;
  status?: TaskRunStatus;
  sandboxAlive?: boolean | null;
  // Why the run itself failed, as the server reports it.
  runError?: string | null;
  // A problem watching the run, such as a lost stream.
  error: string | null;
}

export const emptyRunView: RunView = {
  loaded: false,
  entries: [],
  windowStart: 0,
  loadingOlder: false,
  error: null,
};

export type SessionLogs = (
  taskId: string,
  runId: string,
  options: { limit: number; offset?: number },
) => Promise<TaskRunSessionLogsPage>;

export interface RunSubscription {
  stop(): void;
  loadOlder(): Promise<void>;
}

const OLDER_PAGE_SIZE = 500;

export function applyUpdate(
  view: RunView,
  update: CloudTaskUpdatePayload,
): RunView {
  switch (update.kind) {
    case "snapshot":
      return {
        ...view,
        loaded: true,
        entries: update.newEntries,
        windowStart: update.windowStart ?? 0,
        status: update.status ?? view.status,
        sandboxAlive: update.sandboxAlive ?? view.sandboxAlive,
        runError: update.errorMessage ?? view.runError,
        error: null,
      };
    case "logs":
      return { ...view, entries: [...view.entries, ...update.newEntries] };
    case "status":
      return {
        ...view,
        status: update.status ?? view.status,
        sandboxAlive: update.sandboxAlive ?? view.sandboxAlive,
        runError: update.errorMessage ?? view.runError,
      };
    case "error":
      return { ...view, error: `${update.errorTitle}: ${update.errorMessage}` };
    default:
      return view;
  }
}

const FINISHED: TaskRunStatus[] = ["completed", "failed", "cancelled"];

// The work list polls run state, so it can learn a run has finished before a quiet stream does.
export function withListedRun(
  view: RunView,
  listed: { status?: TaskRunStatus; error_message?: string | null } | undefined,
): RunView {
  if (!listed?.status) return view;
  if (!view.status || FINISHED.includes(listed.status)) {
    return {
      ...view,
      status: listed.status,
      runError: view.runError ?? listed.error_message ?? null,
    };
  }
  return view;
}

// A status line for the pane while a run has nothing of its own to show.
export function runNotice(
  view: RunView,
  lines: TranscriptLine[],
): { text: string; tone: "working" | "error" } | null {
  if (view.status === "failed") {
    return { text: view.runError || "The run failed.", tone: "error" };
  }
  const replied = lines.some((line) => line.kind !== "user");
  if ((view.status === "queued" || view.status === "in_progress") && !replied) {
    return { text: "Starting cloud run…", tone: "working" };
  }
  return null;
}

const keyOf = (taskId: string, runId: string): string => `${taskId}:${runId}`;

// Watches cloud runs through one shared engine and hands each subscriber only its own run.
export class CloudRuns {
  private readonly previews = new Map<string, RunView>();

  constructor(
    private readonly engine: CloudTaskEngine,
    private readonly context: () => Promise<{
      apiHost: string;
      teamId: number;
    }>,
    private readonly sessionLogs: SessionLogs,
  ) {}

  // Fetches the last `entries` log entries so opening the run shows its recent messages at once.
  async prefetch(
    taskId: string,
    runId: string,
    entries: number,
  ): Promise<void> {
    const probe = await this.sessionLogs(taskId, runId, { limit: 1 });
    const total = probe.matchingCount ?? probe.entries.length;
    const windowStart = Math.max(0, total - entries);
    const page = await this.sessionLogs(taskId, runId, {
      limit: total - windowStart,
      offset: windowStart,
    });
    this.previews.set(keyOf(taskId, runId), {
      ...emptyRunView,
      loaded: true,
      entries: page.entries,
      windowStart,
    });
  }

  watch(
    taskId: string,
    runId: string,
    onView: (view: RunView) => void,
    { olderPageSize = OLDER_PAGE_SIZE }: { olderPageSize?: number } = {},
  ): RunSubscription {
    let view = this.previews.get(keyOf(taskId, runId)) ?? emptyRunView;
    let stopped = false;
    const publish = (next: RunView): void => {
      view = next;
      if (!stopped) onView(view);
    };
    if (view.loaded) onView(view);

    const listener = (update: CloudTaskUpdatePayload): void => {
      if (update.taskId !== taskId || update.runId !== runId) return;
      publish(applyUpdate(view, update));
      if (update.kind === "snapshot") {
        this.previews.set(keyOf(taskId, runId), view);
      }
    };
    this.engine.on(CloudTaskEvent.Update, listener);
    this.context().then(
      ({ apiHost, teamId }) => {
        if (!stopped) this.engine.watch({ taskId, runId, apiHost, teamId });
      },
      (error: unknown) =>
        publish({
          ...view,
          error: error instanceof Error ? error.message : String(error),
        }),
    );

    return {
      stop: () => {
        stopped = true;
        this.engine.off(CloudTaskEvent.Update, listener);
        this.engine.unwatch(taskId, runId);
      },
      loadOlder: async () => {
        const windowStart = view.windowStart;
        if (windowStart <= 0 || view.loadingOlder) return;
        publish({ ...view, loadingOlder: true });
        const offset = Math.max(0, windowStart - olderPageSize);
        try {
          const page = await this.sessionLogs(taskId, runId, {
            limit: windowStart - offset,
            offset,
          });
          // A new snapshot may have replaced the window while this page loaded.
          if (view.windowStart !== windowStart) {
            publish({ ...view, loadingOlder: false });
            return;
          }
          publish({
            ...view,
            entries: [...page.entries, ...view.entries],
            windowStart: offset,
            loadingOlder: false,
          });
        } catch (error) {
          publish({
            ...view,
            loadingOlder: false,
            error: error instanceof Error ? error.message : String(error),
          });
        }
      },
    };
  }
}
