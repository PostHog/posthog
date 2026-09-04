import {
  CANVAS_V2_FIELD_MAX_OP_ENTRIES,
  CANVAS_V2_MAX_STATE_VALUE_BYTES,
  type CanvasV2Actor,
  type CanvasV2AppendOpsInput,
  type CanvasV2AppendOpsResult,
  type CanvasV2Board,
  type CanvasV2EditFieldOp,
  type CanvasV2Fragment,
  type CanvasV2LogEntry,
  type CanvasV2Op,
  type CanvasV2OpsPage,
  type CanvasV2Snapshot,
  emptyCanvasV2Snapshot,
  estimateJsonBytes,
  foldOps,
  getBackoffDelay,
} from "@posthog/shared";

/** The board endpoints the sync client needs. Implemented over tRPC by the host. */
export interface BoardApi {
  get(id: string): Promise<CanvasV2Board>;
  opsSince(id: string, since: number, limit?: number): Promise<CanvasV2OpsPage>;
  appendOps(
    id: string,
    input: CanvasV2AppendOpsInput,
  ): Promise<CanvasV2AppendOpsResult>;
}

export type BoardSyncStatus =
  | "loading"
  | "synced"
  | "saving"
  | "offline"
  | "error";

/** A local op that the server has not sequenced yet. */
export interface PendingEntry {
  opId: string;
  op: CanvasV2Op;
  actor: CanvasV2Actor;
  createdAt: string;
}

export interface BoardSyncState {
  boardId: string;
  name: string;
  /** The space the board is filed in, for a share link and a back link. */
  channelId: string | null;
  /** The board at the head: the server snapshot folded with the log and the pending ops. */
  snapshot: CanvasV2Snapshot;
  headSeq: number;
  /** Ascending by seq, deduped by opId. */
  log: CanvasV2LogEntry[];
  /** True when the log starts at seq 1, so it can be folded from an empty board. */
  logComplete: boolean;
  pending: PendingEntry[];
  status: BoardSyncStatus;
  /** True while the board stream is connected, so polling is off. */
  live: boolean;
  lastError?: string;
  fragmentErrors: Record<string, string>;
}

export interface BoardSyncOptions {
  actorUser?: { userId?: number; userName?: string };
  now?: () => number;
  onChange: (state: BoardSyncState) => void;
  flushDebounceMs?: number;
  pollIntervalMs?: number;
  checkpointIntervalMs?: number;
}

const FLUSH_DEBOUNCE_MS = 150;
const POLL_INTERVAL_MS = 1500;
const CHECKPOINT_INTERVAL_MS = 30_000;
const OPS_PAGE_LIMIT = 1000;
const OPS_AFTER_SNAPSHOT_CAP = 2000;
const RETRY_INITIAL_MS = 1000;
const RETRY_MAX_MS = 15_000;
const CATCH_UP_PAGE_BUDGET = 500;
const GEOMETRY_KEYS: readonly string[] = ["x", "y", "w", "h"];

/**
 * One open board: the server log, the local optimistic ops, and the folded
 * snapshot both produce. The head snapshot is always recomputed from
 * `baseSnapshot + log + pending` instead of mutated, so ops that arrive out of
 * order still converge on the same board.
 */
export class BoardSyncClient {
  private readonly api: BoardApi;
  private readonly boardId: string;
  private readonly onChange: (state: BoardSyncState) => void;
  private readonly now: () => number;
  private readonly actorUser?: { userId?: number; userName?: string };
  private readonly flushDebounceMs: number;
  private readonly pollIntervalMs: number;
  private readonly checkpointIntervalMs: number;

  private name = "";
  private baseSnapshot: CanvasV2Snapshot = emptyCanvasV2Snapshot();
  private baseSeq = 0;
  private headSeq = 0;
  private log: CanvasV2LogEntry[] = [];
  private logComplete = false;
  private pending: PendingEntry[] = [];
  private snapshot: CanvasV2Snapshot = emptyCanvasV2Snapshot();
  private fragmentErrors: Record<string, string> = {};
  private lastError: string | undefined;

  private loading = true;
  private loadFailed = false;
  private inFlight = false;
  private inFlightOpIds: ReadonlySet<string> = new Set();
  private flushQueued = false;
  private polling = false;
  private retryAttempt = 0;
  private lastCheckpointAt = 0;
  private visible = true;
  private live = false;
  private started = false;
  private stopped = false;
  private flushTimer: ReturnType<typeof setTimeout> | undefined;
  private retryTimer: ReturnType<typeof setTimeout> | undefined;
  private pollTimer: ReturnType<typeof setInterval> | undefined;
  private state: BoardSyncState;

  constructor(api: BoardApi, boardId: string, opts: BoardSyncOptions) {
    this.api = api;
    this.boardId = boardId;
    this.onChange = opts.onChange;
    this.now = opts.now ?? (() => Date.now());
    this.actorUser = opts.actorUser;
    this.flushDebounceMs = opts.flushDebounceMs ?? FLUSH_DEBOUNCE_MS;
    this.pollIntervalMs = opts.pollIntervalMs ?? POLL_INTERVAL_MS;
    this.checkpointIntervalMs =
      opts.checkpointIntervalMs ?? CHECKPOINT_INTERVAL_MS;
    this.state = this.buildState();
  }

  getState(): BoardSyncState {
    return this.state;
  }

  async load(): Promise<void> {
    this.loading = true;
    this.emit();
    try {
      const board = await this.api.get(this.boardId);
      this.name = board.name;
      this.channelId = board.channelId;
      this.baseSnapshot = board.snapshot;
      this.baseSeq = board.snapshotSeq;
      this.headSeq = board.headSeq;
      this.log = sortLog(dedupeByOpId(board.opsAfterSnapshot));
      this.refreshLogComplete();
      if (board.opsAfterSnapshot.length >= OPS_AFTER_SNAPSHOT_CAP) {
        await this.catchUp();
      }
      this.loadFailed = false;
      this.lastError = undefined;
      this.retryAttempt = 0;
    } catch (error) {
      this.loadFailed = true;
      this.lastError = errorMessage(error);
    } finally {
      this.loading = false;
      this.recompute();
    }
  }

  /** Pages the whole log so the history panel can fold the board from empty. */
  async loadFullLog(): Promise<void> {
    if (this.logComplete) return;
    try {
      let since = 0;
      for (let page = 0; page < CATCH_UP_PAGE_BUDGET; page++) {
        const result = await this.api.opsSince(
          this.boardId,
          since,
          OPS_PAGE_LIMIT,
        );
        this.headSeq = Math.max(this.headSeq, result.headSeq);
        if (result.results.length === 0) break;
        this.ingest(result.results);
        const last = result.results[result.results.length - 1];
        since = last.seq;
        if (since >= this.headSeq) break;
      }
      this.refreshLogComplete();
      this.lastError = undefined;
    } catch (error) {
      this.lastError = errorMessage(error);
    }
    this.recompute();
  }

  /**
   * Records ops locally and sends them. `opIds` lets the caller pass
   * deterministic ids, which is how the same agent tool call applied by two
   * collaborators lands as one op on the server.
   */
  applyLocal(
    ops: CanvasV2Op[],
    actor?: { kind: "user" | "agent"; taskId?: string },
    opIds?: string[],
  ): void {
    const kind = actor?.kind ?? "user";
    const identity: CanvasV2Actor =
      kind === "agent"
        ? { kind: "agent", taskId: actor?.taskId }
        : {
            kind: "user",
            userId: this.actorUser?.userId,
            userName: this.actorUser?.userName,
          };
    const createdAt = new Date(this.now()).toISOString();
    let added = false;

    for (const [index, op] of ops.entries()) {
      if (this.rejectsStateValue(op)) continue;
      const opId = opIds?.[index] ?? newOpId();
      if (this.hasOp(opId)) continue;
      this.appendPending({ opId, op, actor: identity, createdAt });
      added = true;
    }

    if (!added) {
      this.emit();
      return;
    }
    this.recompute();
    this.scheduleFlush();
  }

  hasOp(opId: string): boolean {
    return (
      this.log.some((entry) => entry.opId === opId) ||
      this.pending.some((entry) => entry.opId === opId)
    );
  }

  async flush(): Promise<void> {
    this.clearFlushTimer();
    if (this.inFlight) {
      this.flushQueued = true;
      return;
    }
    const batch = leadingActorRun(this.pending);
    if (batch.length === 0) return;

    const sendsEverything = batch.length === this.pending.length;
    const first = batch[0];
    const input: CanvasV2AppendOpsInput = {
      ops: batch.map((entry) => ({ opId: entry.opId, op: entry.op })),
      actor: { kind: first.actor.kind, taskId: first.actor.taskId },
      baseSeq: this.headSeq,
      snapshot: sendsEverything && this.isCurrent() ? this.snapshot : undefined,
    };
    const sentSnapshot = input.snapshot;

    this.inFlight = true;
    this.inFlightOpIds = new Set(batch.map((entry) => entry.opId));
    this.emit();
    try {
      const result = await this.api.appendOps(this.boardId, input);
      this.promote(batch, result, sentSnapshot);
      this.retryAttempt = 0;
      this.lastError = undefined;
      this.loadFailed = false;
    } catch (error) {
      this.lastError = errorMessage(error);
      if (isRefusedByServer(error)) {
        this.discard(batch);
        void this.load();
      } else {
        this.retryAttempt += 1;
        this.scheduleRetry();
      }
    } finally {
      this.inFlight = false;
      this.inFlightOpIds = new Set();
      this.recompute();
    }

    const queued = this.flushQueued;
    this.flushQueued = false;
    if (this.retryAttempt === 0 && (queued || this.pending.length > 0)) {
      this.scheduleFlush();
    }
  }

  async poll(): Promise<void> {
    if (this.polling) return;
    this.polling = true;
    try {
      const page = await this.api.opsSince(this.boardId, this.headSeq);
      this.headSeq = Math.max(this.headSeq, page.headSeq);
      this.ingest(page.results);
      this.retryAttempt = 0;
      this.lastError = undefined;
      this.loadFailed = false;
      this.recompute();
      void this.maybeCheckpoint();
    } catch (error) {
      this.lastError = errorMessage(error);
      this.emit();
    } finally {
      this.polling = false;
    }
  }

  start(): void {
    this.stopped = false;
    this.started = true;
    this.restartPollTimer();
  }

  stop(): void {
    this.started = false;
    this.stopped = true;
    this.clearFlushTimer();
    this.clearRetryTimer();
    this.clearPollTimer();
    if (this.pending.length > 0) void this.flush();
  }

  setVisible(visible: boolean): void {
    if (this.visible === visible) return;
    this.visible = visible;
    if (visible) {
      this.restartPollTimer();
      void this.poll();
      return;
    }
    this.clearPollTimer();
  }

  /**
   * The stream is the first source of ops. While it is connected the poll
   * timer stops; a drop starts it again and one poll closes the gap.
   */
  setLive(live: boolean): void {
    if (this.live === live) return;
    this.live = live;
    this.restartPollTimer();
    void this.poll();
    this.emit();
  }

  /** One stream op, applied exactly as a polled entry. */
  ingestStreamEntry(entry: CanvasV2LogEntry): void {
    this.headSeq = Math.max(this.headSeq, entry.seq);
    this.ingest([entry]);
    this.recompute();
  }

  setFragmentError(id: string, message: string | null): void {
    const has = id in this.fragmentErrors;
    if (message === null) {
      if (!has) return;
      const next = { ...this.fragmentErrors };
      delete next[id];
      this.fragmentErrors = next;
      this.emit();
      return;
    }
    if (has && this.fragmentErrors[id] === message) return;
    this.fragmentErrors = { ...this.fragmentErrors, [id]: message };
    this.emit();
  }

  /** Appends a `restore` op that sets the board to the board as of `seq`. */
  async restoreTo(seq: number): Promise<void> {
    if (!this.logComplete) await this.loadFullLog();
    if (!this.logComplete) {
      this.lastError = "The full history is not loaded yet.";
      this.emit();
      return;
    }
    const upTo = this.log.filter((entry) => entry.seq <= seq);
    const target = foldOps(emptyCanvasV2Snapshot(), upTo);
    this.applyLocal([{ type: "restore", snapshot: target, toSeq: seq }]);
  }

  /** Restores the board to the seq before this user's last non-restore op. */
  async undoLastOwnOp(): Promise<void> {
    if (this.pending.length > 0) await this.flush();
    const mine = this.log.filter((entry) => this.isOwnEntry(entry));
    const last = mine[mine.length - 1];
    if (!last) return;
    await this.restoreTo(last.seq - 1);
  }

  private isOwnEntry(entry: CanvasV2LogEntry): boolean {
    if (entry.actor.kind !== "user") return false;
    if (entry.op.type === "restore") return false;
    const userId = this.actorUser?.userId;
    if (userId === undefined) return true;
    return entry.actor.userId === userId;
  }

  private rejectsStateValue(op: CanvasV2Op): boolean {
    if (op.type !== "set_state") return false;
    if (estimateJsonBytes(op.value) <= CANVAS_V2_MAX_STATE_VALUE_BYTES) {
      return false;
    }
    this.lastError = `The value for "${op.key}" is too large to share on this board.`;
    return true;
  }

  /**
   * Merges a drag or a burst of typing into one history entry: consecutive
   * geometry-only updates of the same fragment, or consecutive edits of the
   * same field, by the same actor become a single pending op.
   */
  private appendPending(entry: PendingEntry): void {
    const last = this.pending[this.pending.length - 1];
    const openLast =
      last !== undefined && !this.inFlightOpIds.has(last.opId)
        ? last
        : undefined;
    const mergedEdits = openLast ? mergeFieldEdits(openLast, entry) : undefined;
    if (mergedEdits) {
      this.pending = [...this.pending.slice(0, -1), mergedEdits];
      return;
    }
    const mergeable =
      last !== undefined &&
      !this.inFlightOpIds.has(last.opId) &&
      isGeometryUpdate(last.op) &&
      isGeometryUpdate(entry.op) &&
      last.op.type === "update_fragment" &&
      entry.op.type === "update_fragment" &&
      last.op.id === entry.op.id &&
      actorIdentity(last.actor) === actorIdentity(entry.actor);

    if (
      mergeable &&
      last.op.type === "update_fragment" &&
      entry.op.type === "update_fragment"
    ) {
      const merged: PendingEntry = {
        ...last,
        op: {
          type: "update_fragment",
          id: last.op.id,
          patch: { ...last.op.patch, ...entry.op.patch },
        },
      };
      this.pending = [...this.pending.slice(0, -1), merged];
      return;
    }
    this.pending = [...this.pending, entry];
  }

  private promote(
    batch: PendingEntry[],
    result: CanvasV2AppendOpsResult,
    sentSnapshot: CanvasV2Snapshot | undefined,
  ): void {
    const seqByOpId = new Map(result.results.map((r) => [r.opId, r.seq]));
    const sent = new Set(batch.map((entry) => entry.opId));
    const promoted: CanvasV2LogEntry[] = [];
    let maxSeq = 0;

    for (const entry of batch) {
      const seq = seqByOpId.get(entry.opId);
      if (seq === undefined) continue;
      maxSeq = Math.max(maxSeq, seq);
      promoted.push({
        seq,
        opId: entry.opId,
        actor: entry.actor,
        createdAt: entry.createdAt,
        op: entry.op,
      });
    }

    this.pending = this.pending.filter((entry) => !sent.has(entry.opId));
    this.log = sortLog(dedupeByOpId([...this.log, ...promoted]));
    this.headSeq = Math.max(this.headSeq, result.headSeq, maxSeq);
    this.refreshLogComplete();

    // The server keeps the snapshot only when nobody else wrote in between,
    // which is exactly when its head equals the last seq it gave us.
    if (sentSnapshot && maxSeq > 0 && result.headSeq === maxSeq) {
      this.baseSnapshot = sentSnapshot;
      this.baseSeq = maxSeq;
      this.lastCheckpointAt = this.now();
    }

    if (result.headSeq > maxSeq) void this.poll();
  }

  private ingest(entries: readonly CanvasV2LogEntry[]): void {
    if (entries.length === 0) return;
    const known = new Set(this.log.map((entry) => entry.opId));
    const promotedOpIds = new Set<string>();
    const additions: CanvasV2LogEntry[] = [];

    for (const entry of entries) {
      if (known.has(entry.opId)) continue;
      known.add(entry.opId);
      additions.push(entry);
      if (this.pending.some((p) => p.opId === entry.opId)) {
        promotedOpIds.add(entry.opId);
      }
    }

    if (promotedOpIds.size > 0) {
      this.pending = this.pending.filter(
        (entry) => !promotedOpIds.has(entry.opId),
      );
    }
    if (additions.length === 0) return;
    this.log = sortLog([...this.log, ...additions]);
    this.refreshLogComplete();
  }

  private discard(batch: readonly { opId: string }[]): void {
    const dropped = new Set(batch.map((entry) => entry.opId));
    this.pending = this.pending.filter((entry) => !dropped.has(entry.opId));
    this.retryAttempt = 0;
  }

  private async catchUp(): Promise<void> {
    for (let page = 0; page < CATCH_UP_PAGE_BUDGET; page++) {
      const since = this.contiguousHead();
      if (since >= this.headSeq) return;
      const result = await this.api.opsSince(
        this.boardId,
        since,
        OPS_PAGE_LIMIT,
      );
      this.headSeq = Math.max(this.headSeq, result.headSeq);
      if (result.results.length === 0) return;
      this.ingest(result.results);
    }
  }

  private async maybeCheckpoint(): Promise<void> {
    if (this.inFlight || this.pending.length > 0) return;
    if (!this.isCurrent() || this.headSeq <= this.baseSeq) return;
    if (this.now() - this.lastCheckpointAt < this.checkpointIntervalMs) return;

    this.lastCheckpointAt = this.now();
    const seq = this.headSeq;
    const snapshot = this.snapshot;
    this.inFlight = true;
    try {
      const result = await this.api.appendOps(this.boardId, {
        ops: [],
        actor: { kind: "user" },
        baseSeq: seq,
        snapshot,
      });
      if (result.headSeq === seq) {
        this.baseSnapshot = snapshot;
        this.baseSeq = seq;
      }
    } catch {
      // A stale server snapshot costs a newcomer some extra ops, nothing more.
    } finally {
      this.inFlight = false;
      this.emit();
    }
  }

  /** The highest seq we hold with no hole between it and the server snapshot. */
  private contiguousHead(): number {
    let cursor = this.baseSeq;
    for (const entry of this.log) {
      if (entry.seq <= cursor) continue;
      if (entry.seq !== cursor + 1) break;
      cursor = entry.seq;
    }
    return cursor;
  }

  private isCurrent(): boolean {
    return this.contiguousHead() >= this.headSeq;
  }

  private refreshLogComplete(): void {
    const first = this.log[0];
    this.logComplete = first ? first.seq === 1 : this.headSeq === 0;
  }

  private scheduleFlush(): void {
    if (this.stopped || this.flushTimer !== undefined) return;
    this.flushTimer = setTimeout(() => {
      this.flushTimer = undefined;
      void this.flush();
    }, this.flushDebounceMs);
  }

  private scheduleRetry(): void {
    if (this.stopped) return;
    this.clearRetryTimer();
    const delay = getBackoffDelay(this.retryAttempt - 1, {
      initialDelayMs: RETRY_INITIAL_MS,
      maxDelayMs: RETRY_MAX_MS,
    });
    this.retryTimer = setTimeout(() => {
      this.retryTimer = undefined;
      void this.flush();
    }, delay);
  }

  private restartPollTimer(): void {
    this.clearPollTimer();
    if (!this.started || !this.visible || this.live) return;
    this.pollTimer = setInterval(() => {
      void this.poll();
    }, this.pollIntervalMs);
  }

  private clearFlushTimer(): void {
    if (this.flushTimer === undefined) return;
    clearTimeout(this.flushTimer);
    this.flushTimer = undefined;
  }

  private clearRetryTimer(): void {
    if (this.retryTimer === undefined) return;
    clearTimeout(this.retryTimer);
    this.retryTimer = undefined;
  }

  private clearPollTimer(): void {
    if (this.pollTimer === undefined) return;
    clearInterval(this.pollTimer);
    this.pollTimer = undefined;
  }

  private recompute(): void {
    const afterBase = this.log.filter((entry) => entry.seq > this.baseSeq);
    this.snapshot = foldOps(
      foldOps(this.baseSnapshot, afterBase),
      this.pending,
    );
    this.emit();
  }

  private status(): BoardSyncStatus {
    if (this.loading) return "loading";
    if (this.retryAttempt > 0) return "offline";
    if (this.loadFailed) return "error";
    if (this.inFlight || this.pending.length > 0) return "saving";
    return "synced";
  }

  private channelId: string | null = null;

  setName(name: string): void {
    if (this.name === name) return;
    this.name = name;
    this.emit();
  }

  private buildState(): BoardSyncState {
    return {
      boardId: this.boardId,
      name: this.name,
      channelId: this.channelId,
      snapshot: this.snapshot,
      headSeq: this.headSeq,
      log: this.log,
      logComplete: this.logComplete,
      pending: this.pending,
      status: this.status(),
      live: this.live,
      lastError: this.lastError,
      fragmentErrors: this.fragmentErrors,
    };
  }

  private emit(): void {
    this.state = this.buildState();
    this.onChange(this.state);
  }
}

export interface HistoryGroup {
  key: string;
  actor: CanvasV2Actor;
  minuteIso: string;
  firstSeq: number;
  lastSeq: number;
  descriptions: string[];
  fragmentIds: string[];
}

/** One short sentence for a log entry, for the history panel. */
export function describeOp(
  entry: CanvasV2LogEntry,
  before: CanvasV2Snapshot,
): string {
  const op = entry.op;
  switch (op.type) {
    case "add_fragment":
      return `added ${op.fragment.title ?? op.fragment.id}`;
    case "update_fragment": {
      const label = fragmentLabel(before, op.id);
      const patch = op.patch;
      if (patch.code !== undefined) return `edited the code of ${label}`;
      if (patch.title !== undefined) return `renamed ${label}`;
      if (patch.w !== undefined || patch.h !== undefined) {
        return `resized ${label}`;
      }
      if (patch.x !== undefined || patch.y !== undefined) {
        return `moved ${label}`;
      }
      if (patch.z !== undefined) return `brought ${label} to front`;
      return `changed ${label}`;
    }
    case "remove_fragment":
      return `removed ${fragmentLabel(before, op.id)}`;
    case "bring_to_front":
      return `brought ${fragmentLabel(before, op.id)} to front`;
    case "set_state":
      return op.value === null || op.value === undefined
        ? `cleared ${op.key}`
        : `changed ${op.key}`;
    case "edit_field":
      return `edited ${op.key}`;
    case "restore":
      return "restored the board";
  }
}

/**
 * The log as history rows, newest first. `base` is the board before the first
 * entry of `log`, so pass `emptyCanvasV2Snapshot()` for a complete log.
 */
export function groupLogEntries(
  log: CanvasV2LogEntry[],
  base: CanvasV2Snapshot,
): HistoryGroup[] {
  const groups: HistoryGroup[] = [];
  let snapshot = base;
  let current: HistoryGroup | undefined;

  for (const entry of log) {
    const identity = actorIdentity(entry.actor);
    const minuteIso = toMinuteIso(entry.createdAt);
    const sameGroup =
      current !== undefined &&
      current.minuteIso === minuteIso &&
      actorIdentity(current.actor) === identity;

    if (!sameGroup) {
      current = {
        key: `${identity}|${minuteIso}|${entry.seq}`,
        actor: entry.actor,
        minuteIso,
        firstSeq: entry.seq,
        lastSeq: entry.seq,
        descriptions: [],
        fragmentIds: [],
      };
      groups.push(current);
    }

    const group = current;
    if (group) {
      const description = describeOp(entry, snapshot);
      if (!group.descriptions.includes(description)) {
        group.descriptions.push(description);
      }
      const fragmentId = touchedFragmentId(entry.op);
      if (fragmentId && !group.fragmentIds.includes(fragmentId)) {
        group.fragmentIds.push(fragmentId);
      }
      group.lastSeq = entry.seq;
    }
    snapshot = foldOps(snapshot, [entry]);
  }

  return groups.reverse();
}

/** How many other people wrote to the board inside the window. */
export function activeCollaborators(
  log: CanvasV2LogEntry[],
  nowMs: number,
  windowMs = 120_000,
  excludeUserId?: number,
): number {
  const seen = new Set<string>();
  for (const entry of log) {
    const at = Date.parse(entry.createdAt);
    if (Number.isNaN(at) || nowMs - at > windowMs) continue;
    if (
      excludeUserId !== undefined &&
      entry.actor.kind === "user" &&
      entry.actor.userId === excludeUserId
    ) {
      continue;
    }
    seen.add(actorIdentity(entry.actor));
  }
  return seen.size;
}

export function actorIdentity(actor: CanvasV2Actor): string {
  if (actor.kind === "agent") return `agent:${actor.taskId ?? "unknown"}`;
  return `user:${actor.userId ?? actor.userName ?? "me"}`;
}

function fragmentLabel(snapshot: CanvasV2Snapshot, id: string): string {
  const fragment: CanvasV2Fragment | undefined = snapshot.fragments.find(
    (candidate) => candidate.id === id,
  );
  return fragment?.title ?? id;
}

function touchedFragmentId(op: CanvasV2Op): string | undefined {
  switch (op.type) {
    case "add_fragment":
      return op.fragment.id;
    case "update_fragment":
    case "remove_fragment":
    case "bring_to_front":
      return op.id;
    default:
      return undefined;
  }
}

function toMinuteIso(createdAt: string): string {
  const at = Date.parse(createdAt);
  if (Number.isNaN(at)) return createdAt;
  return `${new Date(at).toISOString().slice(0, 16)}:00.000Z`;
}

/** A person types faster than the flush, so one burst leaves one op. */
function mergeFieldEdits(
  last: PendingEntry,
  entry: PendingEntry,
): PendingEntry | undefined {
  if (last.op.type !== "edit_field" || entry.op.type !== "edit_field") {
    return undefined;
  }
  if (last.op.key !== entry.op.key || last.op.kind !== entry.op.kind) {
    return undefined;
  }
  if (actorIdentity(last.actor) !== actorIdentity(entry.actor))
    return undefined;

  const insert = [...(last.op.insert ?? []), ...(entry.op.insert ?? [])];
  const remove = [...(last.op.remove ?? []), ...(entry.op.remove ?? [])];
  if (
    insert.length > CANVAS_V2_FIELD_MAX_OP_ENTRIES ||
    remove.length > CANVAS_V2_FIELD_MAX_OP_ENTRIES
  ) {
    return undefined;
  }
  const op: CanvasV2EditFieldOp = {
    type: "edit_field",
    key: last.op.key,
    kind: last.op.kind,
  };
  if (insert.length > 0) op.insert = insert;
  if (remove.length > 0) op.remove = remove;
  return { ...last, op };
}

function isGeometryUpdate(op: CanvasV2Op): boolean {
  if (op.type !== "update_fragment") return false;
  const keys = Object.keys(op.patch);
  return keys.length > 0 && keys.every((key) => GEOMETRY_KEYS.includes(key));
}

function isRefusedByServer(error: unknown): boolean {
  const data = (
    error as { data?: { code?: unknown; httpStatus?: unknown } } | null
  )?.data;
  return data?.code === "BAD_REQUEST" || data?.httpStatus === 400;
}

/** The longest run at the head of the queue that one appendOps call can carry. */
function leadingActorRun(pending: readonly PendingEntry[]): PendingEntry[] {
  const first = pending[0];
  if (!first) return [];
  const identity = actorIdentity(first.actor);
  const run: PendingEntry[] = [];
  for (const entry of pending) {
    if (actorIdentity(entry.actor) !== identity) break;
    run.push(entry);
  }
  return run;
}

function sortLog(entries: CanvasV2LogEntry[]): CanvasV2LogEntry[] {
  return [...entries].sort((a, b) => a.seq - b.seq);
}

function dedupeByOpId(
  entries: readonly CanvasV2LogEntry[],
): CanvasV2LogEntry[] {
  const seen = new Set<string>();
  const out: CanvasV2LogEntry[] = [];
  for (const entry of entries) {
    if (seen.has(entry.opId)) continue;
    seen.add(entry.opId);
    out.push(entry);
  }
  return out;
}

function newOpId(): string {
  return globalThis.crypto.randomUUID();
}

function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}
