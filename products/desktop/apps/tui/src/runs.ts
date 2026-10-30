import type { PermissionOption } from "@agentclientprotocol/sdk";
import type { TaskRunSessionLogsPage } from "@posthog/api-client/posthog-client";
import type { CloudTaskEngine } from "@posthog/core/cloud-task/cloud-task-engine";
import { CloudTaskEvent } from "@posthog/core/cloud-task/schemas";
import { THINKING_ACTIVITIES } from "@posthog/core/sessions/thinkingActivities";
import {
  type CloudTaskUpdatePayload,
  type StoredLogEntry,
  type TaskRunStatus,
  TRANSCRIPT_TAIL_WINDOW,
} from "@posthog/shared";
import type { ChatNotice } from "./chatView";
import type { AcpQuestion, AgentPrompt, PromptReply } from "./prompts";
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

// A view over a local agent's full log that hands the pane only its tail, as a cloud watch does: the transcript is
// rebuilt on every event, and a long log made that cost a frame. `loadOlder` pages kept entries back in above.
export function windowed(
  onView: (view: RunView) => void,
  { tail = TRANSCRIPT_TAIL_WINDOW, page = OLDER_PAGE_SIZE } = {},
): { publish: (full: RunView) => void; loadOlder: () => void } {
  let full = emptyRunView;
  // How far back the pane has paged; the window never shrinks below it as the log grows.
  let windowStart: number | null = null;
  const show = (): void => {
    const start = Math.min(
      windowStart ?? Math.max(0, full.entries.length - tail),
      Math.max(0, full.entries.length - tail),
    );
    onView({ ...full, entries: full.entries.slice(start), windowStart: start });
  };
  return {
    publish: (next) => {
      full = next;
      show();
    },
    loadOlder: () => {
      const current = windowStart ?? Math.max(0, full.entries.length - tail);
      if (current === 0) return;
      windowStart = Math.max(0, current - page);
      show();
    },
  };
}

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
// How long a run's stream stays open after its last subscriber leaves. Panes and the turn tracker stop and restart
// their subscriptions within one render; a stream closed in that gap reopened at its latest entry and lost, or
// replayed, what landed in between.
const UNWATCH_GRACE_MS = 1_000;
// A sandbox restored from a snapshot usually takes under a minute; past this, the reply gives up.
const AGENT_RESTART_TIMEOUT_MS = 10 * 60_000;
// The server's clock can run a little ahead of this machine's.
const CLOCK_SKEW_MS = 5_000;
// How long a hold waits before watching a run again that still read as finished after its resume.
const REOPEN_MS = 3_000;
// The entries a run keeps once nobody holds it: the preview the work list fetched, not the history paged in.
const IDLE_TAIL = 300;

// The sandbox's agent has reported in: pi writes its own entry, Claude Code and Codex the run_started notification.
export function runStarted(entry: StoredLogEntry): boolean {
  return (
    entry.type === "pi_run_started" ||
    entry.notification?.method === "_posthog/run_started"
  );
}

// A cloud run's agent is up: its start marker is in the window, or a long log has it before the window.
export function agentUp(view: RunView): boolean {
  return view.windowStart > 0 || view.entries.some(runStarted);
}

// A streamed entry can arrive without a timestamp, which the transcript would read as "now" on every redraw, so a finished
// turn's "Worked for" would keep counting. The arrival time is stamped once instead.
function stamped(entries: StoredLogEntry[]): StoredLogEntry[] {
  const now = new Date(Date.now()).toISOString();
  return entries.map((entry) =>
    entry.timestamp ? entry : { ...entry, timestamp: now },
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
        entries: stamped(update.newEntries),
        windowStart: update.windowStart ?? 0,
        status: update.status ?? view.status,
        sandboxAlive: update.sandboxAlive ?? view.sandboxAlive,
        runError: update.errorMessage ?? view.runError,
        error: null,
      };
    case "logs": {
      // A watch resumed by entry count replays the stream from its start, and the engine counts the replay as new.
      const held = new Set(view.entries.map((entry) => entry.event_id));
      const fresh = update.newEntries.filter(
        (entry) => !entry.event_id || !held.has(entry.event_id),
      );
      return { ...view, entries: [...view.entries, ...stamped(fresh)] };
    }
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

// What the hedgehog did, once its turn is over; the turn's end picks one, so a redraw keeps it.
const DONE_WORDS = [
  "Foraged",
  "Snuffled",
  "Rooted around",
  "Burrowed",
  "Trundled",
  "Rummaged",
  "Snouted about",
  "Bristled",
  "Quilled",
  "Nosed around",
  "Grubbed",
  "Prowled",
  "Scurried",
  "Snaffled",
  "Pottered",
  "Beetled",
];
const doneWord = (endedAt: number): string => {
  // A small hash, so turns a millisecond apart get different words.
  let hash = Math.floor(endedAt) >>> 0;
  hash = Math.imul(hash ^ (hash >>> 16), 0x45d9f3b) >>> 0;
  hash = (hash ^ (hash >>> 16)) >>> 0;
  return DONE_WORDS[hash % DONE_WORDS.length];
};

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
  // The backend could not hand the message to the sandbox (it answered 502, or its credentials could not be rebound):
  // a send would fail the same way, so the run has to be brought back first, though the server still counts it as live.
  sandboxGone: boolean;
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
      sandboxGone: /^send_followup failed/.test(
        params.detail?.replace(/^\w*Error: /, "") ?? "",
      ),
    };
  }
  return null;
}

// "2 shells · 1 monitor" from the harness, or a count, as "2 shells still running".
function shellsRunning(shells: string | number | undefined): string | null {
  const count =
    typeof shells === "number"
      ? shells
      : Number(/^(\d+) shell/.exec(shells ?? "")?.[1] ?? 0);
  if (count <= 0) return null;
  return `${count} shell${count === 1 ? "" : "s"} still running`;
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
    shells,
  }: {
    setup?: SetupProgress | null;
    compacting?: boolean;
    // The wake-up the agent scheduled at the end of its last turn.
    wake?: Transcript["wake"];
    // Background shells still running after the turn: the harness's status line, or a count.
    shells?: string | number;
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
    const worked = `${doneWord(lastTurn.endedAt)} for ${formatDuration(lastTurn.durationMs)}`;
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
    const stillRunning = running ? shellsRunning(shells) : null;
    return {
      text: `${worked} · done ${done}${stillRunning ? ` · ${stillRunning}` : ""}`,
      tone: "done",
    };
  }
  return null;
}

const keyOf = (taskId: string, runId: string): string => `${taskId}:${runId}`;

// A run as the store holds it: one view that every subscriber reads, and one engine watch while anyone does.
interface RunEntry {
  taskId: string;
  runId: string;
  view: RunView;
  listeners: Set<(view: RunView) => void>;
  // Subscribers plus holds; the engine watch closes a grace period after this reaches zero.
  refs: number;
  // This store asked the engine to watch the run and has not released it. The engine stops a run's watcher by
  // itself once the run ends, so a finished run's entry opens a new watch for its next subscriber.
  opened: boolean;
  opening: boolean;
  // The entry's engine listener is registered; it stays through the grace period after the last reference goes.
  listening: boolean;
  release: NodeJS.Timeout | null;
  onUpdate: (update: CloudTaskUpdatePayload) => void;
  // Entries paged in from earlier runs, and how many each earlier run still holds above them.
  earlierEntries: StoredLogEntry[];
  earlier: { runId: string; remaining: number }[];
  earlierProbed: boolean;
}

// Watches cloud runs through one shared engine, keeping one view per run that every pane and the turn tracker read.
export class CloudRuns {
  private readonly runs = new Map<string, RunEntry>();

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
    private readonly unwatchGraceMs = UNWATCH_GRACE_MS,
    // How many entries a run keeps once nobody holds it; the rest pages back in on the next scroll up.
    private readonly idleTail = IDLE_TAIL,
  ) {}

  // What a cloud run waits on the user for, by task: a Claude Code or Codex permission request, or the engine's
  // approval of a relayed MCP call. Answered through the engine, which keeps a relay approval to itself.
  private prompts = new Map<string, AgentPrompt[]>();
  private readonly taskOfRun = new Map<string, string>();
  private readonly promptListeners = new Set<
    (prompts: Map<string, AgentPrompt[]>) => void
  >();
  private promptListener?: (update: CloudTaskUpdatePayload) => void;

  watchPrompts(
    onPrompts: (prompts: Map<string, AgentPrompt[]>) => void,
  ): () => void {
    if (!this.promptListener) {
      this.promptListener = (update) => {
        if (update.kind === "permission_request") {
          const meta = update.toolCall._meta as
            | { codeToolKind?: string; questions?: AcpQuestion[] }
            | undefined;
          const questions =
            meta?.codeToolKind === "question" && Array.isArray(meta.questions)
              ? meta.questions
              : undefined;
          this.taskOfRun.set(update.runId, update.taskId);
          this.setPrompts(update.taskId, [
            ...(this.prompts.get(update.taskId) ?? []),
            {
              kind: "acp",
              request: {
                taskRunId: update.runId,
                // The request id is what the engine answers by; the sandbox's own call id is not needed again.
                toolCallId: update.requestId,
                title: update.toolCall.title,
                // The sandbox's options name ACP's kinds; the shared type only says string.
                options: update.options as PermissionOption[],
                ...(questions && { questions }),
              },
            },
          ]);
        } else if (
          (update.kind === "status" || update.kind === "snapshot") &&
          update.status &&
          FINISHED.includes(update.status)
        ) {
          this.setPrompts(
            update.taskId,
            (this.prompts.get(update.taskId) ?? []).filter(
              (prompt) =>
                prompt.kind !== "acp" ||
                prompt.request.taskRunId !== update.runId,
            ),
          );
        }
      };
      this.engine.on(CloudTaskEvent.Update, this.promptListener);
    }
    this.promptListeners.add(onPrompts);
    onPrompts(this.prompts);
    return () => {
      this.promptListeners.delete(onPrompts);
      if (this.promptListeners.size === 0 && this.promptListener) {
        this.engine.off(CloudTaskEvent.Update, this.promptListener);
        this.promptListener = undefined;
      }
    };
  }

  private setPrompts(taskId: string, prompts: AgentPrompt[]): void {
    this.prompts = new Map(this.prompts).set(taskId, prompts);
    for (const listener of this.promptListeners) listener(this.prompts);
  }

  async answer(reply: PromptReply): Promise<void> {
    if (reply.kind !== "acp") return;
    const taskId = this.taskOfRun.get(reply.taskRunId);
    if (!taskId) return;
    this.setPrompts(
      taskId,
      (this.prompts.get(taskId) ?? []).filter(
        (prompt) =>
          prompt.kind !== "acp" ||
          prompt.request.toolCallId !== reply.toolCallId,
      ),
    );
    const result = await this.engine.sendCommand({
      taskId,
      runId: reply.taskRunId,
      ...(await this.context()),
      method: "permission_response",
      params: {
        requestId: reply.toolCallId,
        optionId: reply.optionId,
        ...(reply.customInput && { customInput: reply.customInput }),
        ...(reply.answers && { answers: reply.answers }),
      },
    });
    if (!result.success)
      throw new Error(result.error ?? "The run did not take the answer");
  }

  private entryFor(taskId: string, runId: string): RunEntry {
    const key = keyOf(taskId, runId);
    const existing = this.runs.get(key);
    if (existing) return existing;
    const entry: RunEntry = {
      taskId,
      runId,
      view: emptyRunView,
      listeners: new Set(),
      refs: 0,
      opened: false,
      opening: false,
      listening: false,
      release: null,
      onUpdate: (update) => {
        if (update.taskId !== taskId || update.runId !== runId) return;
        this.publish(entry, applyUpdate(entry.view, update));
        // The engine drops its watcher once the run ends; the next subscriber opens a new one.
        if (
          (update.kind === "snapshot" || update.kind === "status") &&
          update.status &&
          FINISHED.includes(update.status)
        )
          entry.opened = false;
      },
      earlierEntries: [],
      earlier: [],
      earlierProbed: false,
    };
    this.runs.set(key, entry);
    return entry;
  }

  private compose(entry: RunEntry): RunView {
    return {
      ...entry.view,
      entries: [...entry.earlierEntries, ...entry.view.entries],
      windowStart:
        entry.view.windowStart +
        entry.earlier.reduce((sum, run) => sum + run.remaining, 0),
    };
  }

  private publish(entry: RunEntry, view: RunView): void {
    entry.view = view;
    const composed = this.compose(entry);
    for (const listener of entry.listeners) listener(composed);
  }

  // Takes a reference on the run's stream, opening it if nobody holds it.
  private acquire(taskId: string, runId: string): RunEntry {
    const entry = this.entryFor(taskId, runId);
    if (entry.release) {
      clearTimeout(entry.release);
      entry.release = null;
    }
    if (!entry.listening) {
      entry.listening = true;
      this.engine.on(CloudTaskEvent.Update, entry.onUpdate);
    }
    entry.refs++;
    this.ensureWatching(entry);
    return entry;
  }

  // Drops a reference; the stream closes once none is left for the grace period.
  private release(entry: RunEntry): void {
    entry.refs--;
    if (entry.refs > 0) return;
    entry.release = setTimeout(() => {
      entry.release = null;
      if (entry.refs > 0) return;
      this.engine.off(CloudTaskEvent.Update, entry.onUpdate);
      entry.listening = false;
      if (entry.opened) this.engine.unwatch(entry.taskId, entry.runId);
      entry.opened = false;
      this.trim(entry);
    }, this.unwatchGraceMs);
    entry.release.unref?.();
  }

  // Drops the history a run paged in while it was read, keeping its tail; earlier runs are probed again when needed.
  private trim(entry: RunEntry): void {
    const dropped = Math.max(0, entry.view.entries.length - this.idleTail);
    entry.view = {
      ...entry.view,
      entries: entry.view.entries.slice(dropped),
      windowStart: entry.view.windowStart + dropped,
    };
    entry.earlierEntries = [];
    entry.earlier = [];
    entry.earlierProbed = false;
  }

  private ensureWatching(entry: RunEntry): void {
    if (entry.opened || entry.opening) return;
    entry.opening = true;
    this.context().then(
      ({ apiHost, teamId }) => {
        entry.opening = false;
        if (entry.refs === 0 || entry.opened) return;
        entry.opened = true;
        this.engine.watch({
          taskId: entry.taskId,
          runId: entry.runId,
          apiHost,
          teamId,
        });
      },
      (error: unknown) => {
        entry.opening = false;
        this.publish(entry, {
          ...entry.view,
          error: error instanceof Error ? error.message : String(error),
        });
      },
    );
  }

  // Resolves once a run brought back with `resume_in_cloud` has its agent running again, after `since` (epoch ms).
  // The hold keeps the run's stream open meanwhile, so the sandbox's one request for its plan's token is answered
  // even if every pane leaves the chat. A stream still reading the run's previous life starts over, so it reads
  // the resumed run; one the engine already closed when that life ended opens anew. The backend answers the resume
  // before the run's status leaves its finished state, and the engine drops a watch opened on a finished run, so
  // the hold opens it again until the run is live; a failure counts as the restart's own only once it was.
  agentRestarted(
    taskId: string,
    runId: string,
    since: number,
    timeoutMs = AGENT_RESTART_TIMEOUT_MS,
    reopenMs = REOPEN_MS,
  ): Promise<void> {
    return new Promise((resolve, reject) => {
      let settled = false;
      let live = false;
      let reopen: NodeJS.Timeout | null = null;
      const entry = this.acquire(taskId, runId);
      if (entry.opened) void this.engine.retry(taskId, runId);
      const finish = (error?: Error): void => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        if (reopen) clearTimeout(reopen);
        this.engine.off(CloudTaskEvent.Update, listener);
        this.release(entry);
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
        if (update.kind !== "snapshot" && update.kind !== "status") return;
        if (!update.status) return;
        if (!FINISHED.includes(update.status)) {
          live = true;
          return;
        }
        if (
          live &&
          (update.status === "failed" || update.status === "cancelled")
        ) {
          finish(
            new Error(update.errorMessage || "The sandbox didn't come back"),
          );
          return;
        }
        // Still the previous life's end: the engine has dropped the watch, so open it again once the status can have moved.
        if (reopen) return;
        reopen = setTimeout(() => {
          reopen = null;
          if (!settled) this.ensureWatching(entry);
        }, reopenMs);
      };
      const timer = setTimeout(
        () => finish(new Error("The sandbox took too long to come back")),
        timeoutMs,
      );
      this.engine.on(CloudTaskEvent.Update, listener);
    });
  }

  // The run's view as the store holds it, streamed or prefetched, for a reader that opens no stream of its own.
  preview(taskId: string, runId: string): RunView | undefined {
    const view = this.runs.get(keyOf(taskId, runId))?.view;
    return view?.loaded ? view : undefined;
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
    const entry = this.entryFor(taskId, runId);
    // A run already on screen has a view of its own that the stream keeps current.
    if (entry.view.loaded) return;
    entry.view = {
      ...emptyRunView,
      loaded: true,
      entries: page.entries,
      windowStart,
    };
  }

  watch(
    taskId: string,
    runId: string,
    onView: (view: RunView) => void,
    {
      olderPageSize = OLDER_PAGE_SIZE,
      withEarlierRuns = false,
    }: { olderPageSize?: number; withEarlierRuns?: boolean } = {},
  ): RunSubscription {
    const entry = this.acquire(taskId, runId);
    entry.listeners.add(onView);
    if (entry.view.loaded) onView(this.compose(entry));
    // Only each earlier run's size is read up front; its entries load as the reader scrolls up to them.
    if (withEarlierRuns && this.earlierRuns && !entry.earlierProbed) {
      entry.earlierProbed = true;
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
            entry.earlier.push(...sizes.filter((run) => run.remaining > 0));
            if (entry.earlier.length > 0) this.publish(entry, entry.view);
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
      this.publish(entry, { ...entry.view, loadingOlder: true });
      try {
        place(await read());
        this.publish(entry, { ...entry.view, loadingOlder: false });
      } catch (error) {
        this.publish(entry, {
          ...entry.view,
          loadingOlder: false,
          error: error instanceof Error ? error.message : String(error),
        });
      }
    };

    let stopped = false;
    return {
      stop: () => {
        if (stopped) return;
        stopped = true;
        entry.listeners.delete(onView);
        this.release(entry);
      },
      loadOlder: async () => {
        if (entry.view.loadingOlder) return;
        const windowStart = entry.view.windowStart;
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
              if (entry.view.windowStart !== windowStart) return;
              entry.view = {
                ...entry.view,
                entries: [...entries, ...entry.view.entries],
                windowStart: offset,
              };
            },
          );
          return;
        }
        const next = entry.earlier.find((run) => run.remaining > 0);
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
            entry.earlierEntries = [...entries, ...entry.earlierEntries];
            next.remaining = offset;
          },
        );
      },
    };
  }
}
