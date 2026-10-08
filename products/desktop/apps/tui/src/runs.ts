import type { TaskRunSessionLogsPage } from "@posthog/api-client/posthog-client";
import type { CloudTaskEngine } from "@posthog/core/cloud-task/cloud-task-engine";
import { CloudTaskEvent } from "@posthog/core/cloud-task/schemas";
import { THINKING_ACTIVITIES } from "@posthog/core/sessions/thinkingActivities";
import type {
  CloudTaskUpdatePayload,
  StoredLogEntry,
  TaskRunStatus,
} from "@posthog/shared";
import type { ChatNotice } from "./chatView";
import {
  activityOf,
  PENDING_ID,
  queuedMessage,
  type Transcript,
  type TranscriptLine,
} from "./transcript";

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
  // A chat running on this machine rather than in a cloud sandbox.
  local?: boolean;
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
// A sandbox restored from a snapshot usually takes under a minute; past this, the reply gives up.
const AGENT_RESTART_TIMEOUT_MS = 10 * 60_000;
// The server's clock can run a little ahead of this machine's.
const CLOCK_SKEW_MS = 5_000;

// The sandbox's agent has reported in: pi writes its own entry, Claude Code and Codex the run_started notification.
export function runStarted(entry: StoredLogEntry): boolean {
  return (
    entry.type === "pi_run_started" ||
    entry.notification?.method === "_posthog/run_started"
  );
}

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
export function formatDuration(ms: number): string {
  // The shared conversation builder can close a turn with its negated start time still in place.
  const seconds = Math.max(0, Math.round(ms / 1000));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (hours > 0) return `${hours}h ${minutes}m`;
  if (minutes > 0) return `${minutes}m ${seconds % 60}s`;
  return `${seconds}s`;
}

const IDLE_WORD_MS = 4_000;
// The desktop app's hedgehog words for a wait, a new one every few seconds; the stride scatters their order.
const idleWord = (now: number): string =>
  THINKING_ACTIVITIES[
    (Math.floor(now / IDLE_WORD_MS) * 7919) % THINKING_ACTIVITIES.length
  ];

export interface SetupStep {
  step: string;
  label: string;
  status: "in_progress" | "completed" | "failed";
  detail?: string;
}

export interface SetupProgress {
  // The step under way, or the last one to finish while the next has not begun.
  current: SetupStep;
  // When this setup began (epoch ms).
  startedAt: number;
  // The agent is ready, so the chat's own state takes over.
  done: boolean;
}

// The steps a sandbox goes through before its agent can reply. Later notices in the group, such as a sandbox
// about to stop, come after setup and do not reopen it.
const SETUP_STEPS = new Set([
  "sandbox",
  "clone",
  "checkout",
  "wizard",
  "agent",
]);

// The backend logs each setup step of a cloud run as a progress notification, grouped by run. Bringing the same
// run back writes a new setup into that group, so only the latest one, from its sandbox step on, counts.
export function setupProgress(
  entries: StoredLogEntry[],
  runId: string,
): SetupProgress | null {
  const group = `setup:${runId}`;
  let steps = new Map<string, SetupStep & { at: number }>();
  let startedAt = 0;
  for (const entry of entries) {
    const notification = (
      entry as { notification?: { method?: string; params?: unknown } }
    ).notification;
    if (notification?.method !== "_posthog/progress") continue;
    const params = notification.params as Partial<SetupStep> & {
      group?: string;
    };
    if (
      params?.group !== group ||
      !params.step ||
      !params.label ||
      !SETUP_STEPS.has(params.step)
    )
      continue;
    const at = Date.parse(entry.timestamp ?? "") || 0;
    if (params.step === "sandbox" && params.status === "in_progress") {
      const previous = steps.get("sandbox");
      // A new setup starts, unless this only restarts the sandbox step within the current one.
      if (!previous || previous.status !== "in_progress") {
        steps = new Map();
        startedAt = at;
      }
    }
    steps.set(params.step, {
      step: params.step,
      label: params.label,
      status: params.status ?? "in_progress",
      ...(params.detail ? { detail: params.detail } : {}),
      at,
    });
  }
  if (steps.size === 0) return null;
  const all = [...steps.values()];
  const latest = (list: typeof all) =>
    list.reduce<(typeof all)[number] | undefined>(
      (last, step) => (!last || step.at >= last.at ? step : last),
      undefined,
    );
  const failed = all.find((step) => step.status === "failed");
  const running = latest(all.filter((step) => step.status === "in_progress"));
  const { at: _, ...current } = (failed ??
    running ??
    latest(all)) as (typeof all)[number];
  return {
    current,
    startedAt: startedAt || Math.min(...all.map((step) => step.at)),
    done: steps.get("agent")?.status === "completed",
  };
}

export interface DeliveryFailure {
  // When the backend gave up on the message (epoch ms).
  at: number;
  text: string;
}

// The backend hands a cloud chat's message to its agent as a follow-up, and logs one it could not deliver as a failed
// `followup_delivery` step. Until the chat moves on, the last message went nowhere.
export function deliveryFailure(
  entries: StoredLogEntry[],
): DeliveryFailure | null {
  for (let index = entries.length - 1; index >= 0; index--) {
    const entry = entries[index];
    if (entry.type === "pi_event") {
      const kind = (entry.event as { type?: string } | undefined)?.type;
      if (
        kind === "user_message" ||
        kind === "turn_completed" ||
        kind === "assistant_message_chunk"
      )
        return null;
      continue;
    }
    const notification = (
      entry as { notification?: { method?: string; params?: unknown } }
    ).notification;
    if (notification?.method !== "_posthog/progress") continue;
    const params = notification.params as Partial<SetupStep> | undefined;
    if (params?.step !== "followup_delivery") continue;
    if (params.status !== "failed") return null;
    const label = params.label || "Couldn't deliver your message";
    // The detail carries the backend's exception prefix, which says nothing to the reader.
    const detail = params.detail
      ?.replace(/^\w*Error: /, "")
      .replace(/^send_followup failed: /, "");
    return {
      at: Date.parse(entry.timestamp ?? "") || 0,
      text: detail ? `${label}: ${detail}` : label,
    };
  }
  return null;
}

export function runNotice(
  view: RunView,
  allLines: TranscriptLine[],
  turnOpen: boolean,
  lastTurn: Transcript["lastTurn"],
  turnStartedAt: number | null = null,
  {
    setup = null,
    reopening = false,
    delivery = null,
    compacting = false,
    wake = null,
  }: {
    setup?: SetupProgress | null;
    compacting?: boolean;
    // The wake-up the agent scheduled at the end of its last turn.
    wake?: Transcript["wake"];
    // The backend could not hand the last message to the agent.
    delivery?: DeliveryFailure | null;
    // A reply is bringing the chat's stopped run back, until its agent takes the message.
    reopening?: boolean;
  } = {},
): ChatNotice | null {
  // A message the agent has not read yet leaves the status on the step it is still taking.
  const lines = queuedMessage(allLines, turnOpen)
    ? allLines.slice(0, -1)
    : allLines;
  const reopeningRun =
    view.status === "queued" || view.status === "in_progress";
  // Until the backend reports the new setup, the wait is for the sandbox to come back.
  if (reopening && (!reopeningRun || !setup || setup.done)) {
    return { text: "Reopening sandbox…", tone: "working" };
  }
  if (view.status === "failed") {
    return { text: view.runError || "The run failed.", tone: "error" };
  }
  const running = view.status === "queued" || view.status === "in_progress";
  // While the sandbox sets up, its current step says what the wait is for.
  if (running && setup && !setup.done) {
    const { current } = setup;
    if (current.status === "failed")
      return {
        text: current.detail
          ? `${current.label} failed: ${current.detail}`
          : `${current.label} failed`,
        tone: "error",
      };
    return {
      text:
        current.status === "in_progress" ? `${current.label}…` : current.label,
      ...(current.detail ? { subject: current.detail } : {}),
      detail: formatDuration(Date.now() - setup.startedAt),
      tone: "working",
    };
  }
  // A message the chat has echoed opens its own turn, so outside a turn only an unsent message waits.
  const waiting =
    lines.at(-1)?.kind === "user" &&
    (turnOpen || lines.at(-1)?.id === PENDING_ID);
  if (running && delivery && !turnOpen && !waiting) {
    return { text: delivery.text, tone: "error" };
  }
  // A local agent is up before its view exists, so only a cloud run has a start-up wait.
  if (!view.local && running && !lines.some((line) => line.kind !== "user")) {
    return { text: "Starting cloud run…", tone: "working" };
  }
  if (running && compacting) return { text: "Compacting…", tone: "working" };
  // A turn still going, or a message the agent has not picked up yet.
  if (running && (turnOpen || waiting)) {
    if (turnStartedAt === null || waiting)
      return { text: "Thinking…", tone: "working" };
    const since = lines.findLastIndex((line) => line.kind === "user");
    const tools = lines
      .slice(since + 1)
      .filter((line) => line.kind === "tool").length;
    // A call still in flight names the work; between calls the agent is thinking it over.
    const last = lines.at(-1);
    const call =
      last?.kind === "tool" &&
      (last.status === "pending" || last.status === "in_progress")
        ? last
        : null;
    const parts = [formatDuration(Date.now() - turnStartedAt)];
    if (tools > 0) parts.push(`${tools} tool${tools === 1 ? "" : "s"}`);
    const subject = call?.detail.split("\n")[0];
    return {
      text: call ? activityOf(call) : `${idleWord(Date.now())}…`,
      ...(subject ? { subject } : {}),
      detail: parts.join(" · "),
      tone: "working",
    };
  }
  if (lastTurn?.stopReason === "error" && !waiting) {
    return {
      text: "The agent stopped on an error. Send a message to try again.",
      tone: "error",
    };
  }
  if (lastTurn && !waiting) {
    const worked = `Worked for ${formatDuration(lastTurn.durationMs)}`;
    // The agent sleeps until its wake-up, so the chat says what it waits on instead of calling the turn done.
    if (wake && running) {
      return {
        text: `${worked} · waiting`,
        ...(wake.reason ? { subject: wake.reason } : {}),
        tone: "done",
      };
    }
    const done = new Date(lastTurn.endedAt).toLocaleTimeString("en-US", {
      hour: "numeric",
      minute: "2-digit",
    });
    return {
      text: `${worked} · done ${done}`,
      tone: "done",
    };
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
    // The task's estimated cost in USD so far, the figure the desktop shows.
    readonly taskCost?: (taskId: string) => Promise<number>,
    // The task's runs before this one, newest first.
    private readonly earlierRuns?: (
      taskId: string,
      runId: string,
    ) => Promise<string[]>,
  ) {}

  // Open watches by run, so a run brought back can be watched again for its panes.
  private readonly watching = new Map<string, number>();

  // Resolves once a run brought back with `resume_in_cloud` has its agent running again, after `since` (epoch ms).
  // The engine stops watching a run once it ends, so the run is watched again to see it come back.
  agentRestarted(
    taskId: string,
    runId: string,
    since: number,
    timeoutMs = AGENT_RESTART_TIMEOUT_MS,
  ): Promise<void> {
    const key = keyOf(taskId, runId);
    return new Promise((resolve, reject) => {
      let settled = false;
      // Set when this wait opened the watch, rather than restarting the panes' one.
      let opened = false;
      const finish = (error?: Error): void => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        this.engine.off(CloudTaskEvent.Update, listener);
        // A watch opened only for this wait closes with it; one the panes rely on stays.
        if (opened && !this.watching.get(key))
          this.engine.unwatch(taskId, runId);
        if (error) reject(error);
        else resolve();
      };
      const started = (entries: StoredLogEntry[]): boolean =>
        entries.some(
          (entry) =>
            runStarted(entry) &&
            (Date.parse(entry.timestamp ?? "") || 0) >= since - CLOCK_SKEW_MS,
        );
      const listener = (update: CloudTaskUpdatePayload): void => {
        if (update.taskId !== taskId || update.runId !== runId) return;
        if (
          (update.kind === "snapshot" || update.kind === "logs") &&
          started(update.newEntries)
        ) {
          finish();
          return;
        }
        if (
          (update.kind === "snapshot" || update.kind === "status") &&
          (update.status === "failed" || update.status === "cancelled")
        )
          finish(
            new Error(update.errorMessage || "The sandbox didn't come back"),
          );
      };
      const timer = setTimeout(
        () => finish(new Error("The sandbox took too long to come back")),
        timeoutMs,
      );
      this.engine.on(CloudTaskEvent.Update, listener);
      this.context().then(
        ({ apiHost, teamId }) => {
          if (settled) return;
          // An open watcher still streams the run's previous life, and stops when that stream ends, so it starts
          // over from the resumed run. Without one, a new watch also serves the panes that lost theirs.
          if (this.engine.isWatching(taskId, runId)) {
            void this.engine.retry(taskId, runId);
          } else {
            opened = true;
            this.engine.watch({ taskId, runId, apiHost, teamId });
          }
        },
        (error: unknown) =>
          finish(error instanceof Error ? error : new Error(String(error))),
      );
    });
  }

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

  // A pi task's runs share one pi session, so with `withEarlierRuns` the earlier runs' logs page in above this
  // run's, oldest last, and a restart that started a new sandbox still shows the whole chat.
  watch(
    taskId: string,
    runId: string,
    onView: (view: RunView) => void,
    {
      olderPageSize = OLDER_PAGE_SIZE,
      withEarlierRuns = false,
    }: { olderPageSize?: number; withEarlierRuns?: boolean } = {},
  ): RunSubscription {
    let own = this.previews.get(keyOf(taskId, runId)) ?? emptyRunView;
    let stopped = false;
    const key = keyOf(taskId, runId);
    this.watching.set(key, (this.watching.get(key) ?? 0) + 1);
    // Entries paged in from earlier runs, and how many each earlier run still holds above them.
    let earlierEntries: StoredLogEntry[] = [];
    const earlier: { runId: string; remaining: number }[] = [];
    const compose = (): RunView => ({
      ...own,
      entries: [...earlierEntries, ...own.entries],
      windowStart:
        own.windowStart + earlier.reduce((sum, run) => sum + run.remaining, 0),
    });
    const publish = (next: RunView): void => {
      own = next;
      if (!stopped) onView(compose());
    };
    if (own.loaded) onView(compose());

    const listener = (update: CloudTaskUpdatePayload): void => {
      if (update.taskId !== taskId || update.runId !== runId) return;
      publish(applyUpdate(own, update));
      if (update.kind === "snapshot") {
        this.previews.set(keyOf(taskId, runId), own);
      }
    };
    this.engine.on(CloudTaskEvent.Update, listener);
    this.context().then(
      ({ apiHost, teamId }) => {
        if (!stopped) this.engine.watch({ taskId, runId, apiHost, teamId });
      },
      (error: unknown) =>
        publish({
          ...own,
          error: error instanceof Error ? error.message : String(error),
        }),
    );
    // Only each earlier run's size is read up front; its entries load as the reader scrolls up to them.
    if (withEarlierRuns && this.earlierRuns) {
      this.earlierRuns(taskId, runId)
        .then((runIds) =>
          Promise.all(
            runIds.map(async (earlierRunId) => {
              const probe = await this.sessionLogs(taskId, earlierRunId, {
                limit: 1,
              });
              return {
                runId: earlierRunId,
                remaining: probe.matchingCount ?? probe.entries.length,
              };
            }),
          ),
        )
        .then(
          (sizes) => {
            earlier.push(...sizes.filter((run) => run.remaining > 0));
            if (earlier.length > 0) publish(own);
          },
          // Without the earlier runs, the chat still shows this run's own log.
          () => {},
        );
    }

    // Loads one older page and places it, showing the load while it runs.
    const pageIn = async (
      read: () => Promise<StoredLogEntry[]>,
      place: (entries: StoredLogEntry[]) => void,
    ): Promise<void> => {
      publish({ ...own, loadingOlder: true });
      try {
        place(await read());
        publish({ ...own, loadingOlder: false });
      } catch (error) {
        publish({
          ...own,
          loadingOlder: false,
          error: error instanceof Error ? error.message : String(error),
        });
      }
    };

    return {
      stop: () => {
        if (!stopped) this.watching.set(key, (this.watching.get(key) ?? 1) - 1);
        stopped = true;
        this.engine.off(CloudTaskEvent.Update, listener);
        this.engine.unwatch(taskId, runId);
      },
      loadOlder: async () => {
        if (own.loadingOlder) return;
        const windowStart = own.windowStart;
        if (windowStart > 0) {
          const offset = Math.max(0, windowStart - olderPageSize);
          await pageIn(
            async () =>
              (
                await this.sessionLogs(taskId, runId, {
                  limit: windowStart - offset,
                  offset,
                })
              ).entries,
            (entries) => {
              // A new snapshot may have replaced the window while this page loaded.
              if (own.windowStart !== windowStart) return;
              own = {
                ...own,
                entries: [...entries, ...own.entries],
                windowStart: offset,
              };
            },
          );
          return;
        }
        const next = earlier.find((run) => run.remaining > 0);
        if (!next) return;
        const end = next.remaining;
        const offset = Math.max(0, end - olderPageSize);
        await pageIn(
          async () =>
            (
              await this.sessionLogs(taskId, next.runId, {
                limit: end - offset,
                offset,
              })
            ).entries,
          (entries) => {
            earlierEntries = [...entries, ...earlierEntries];
            next.remaining = offset;
          },
        );
      },
    };
  }
}
