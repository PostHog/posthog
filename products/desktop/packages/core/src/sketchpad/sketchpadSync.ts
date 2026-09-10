import {
  emptySketchpadSnapshot,
  estimateJsonBytes,
  foldOps,
  getBackoffDelay,
  SKETCHPAD_FIELD_MAX_OP_ENTRIES,
  SKETCHPAD_MAX_STATE_VALUE_BYTES,
  type SketchpadActor,
  type SketchpadAppendOpsInput,
  type SketchpadAppendOpsResult,
  type SketchpadEditFieldOp,
  type SketchpadFragment,
  type SketchpadLogEntry,
  type SketchpadOp,
  type SketchpadSnapshot,
  sketchpadLogEntrySchema,
} from "@posthog/shared";
import type { StateStorage } from "zustand/middleware";
import { createStore, type StoreApi } from "zustand/vanilla";
import type { ISketchpadService } from "./identifiers";

export type SketchpadApi = Pick<
  ISketchpadService,
  "get" | "opsSince" | "appendOps"
>;

export type SketchpadSyncStatus =
  | "loading"
  | "synced"
  | "saving"
  | "offline"
  | "error";

export type PendingEntry = Omit<SketchpadLogEntry, "seq">;

export interface SketchpadSyncState {
  sketchpadId: string;
  name: string;
  channelId: string | null;
  snapshot: SketchpadSnapshot;
  headSeq: number;
  log: SketchpadLogEntry[];
  logComplete: boolean;
  pending: PendingEntry[];
  status: SketchpadSyncStatus;
  live: boolean;
  lastError?: string;
  fragmentErrors: Record<string, string>;
}

export interface SketchpadSyncOptions {
  actorUser?: { userId?: number; userName?: string };
  now?: () => number;
  flushDebounceMs?: number;
  pollIntervalMs?: number;
  pendingStorage?: { storage: StateStorage; key: string };
}

const FLUSH_DEBOUNCE_MS = 150;
const POLL_INTERVAL_MS = 1500;
const OPS_PAGE_LIMIT = 1000;
const RETRY_INITIAL_MS = 1000;
const RETRY_MAX_MS = 15_000;
const CATCH_UP_PAGE_BUDGET = 500;
const GEOMETRY_KEYS: readonly string[] = ["x", "y", "w", "h"];

export class SketchpadSyncClient {
  private readonly api: SketchpadApi;
  private readonly sketchpadId: string;
  private readonly now: () => number;
  private actorUser?: { userId?: number; userName?: string };
  private readonly flushDebounceMs: number;
  private readonly pollIntervalMs: number;
  private readonly pendingStorage: SketchpadSyncOptions["pendingStorage"];
  private pendingLoaded = false;
  private savedPending: PendingEntry[] = [];

  private name = "";
  private baseSnapshot: SketchpadSnapshot = emptySketchpadSnapshot();
  private baseSeq = 0;
  private foldedBase = this.baseSnapshot;
  private foldedSnapshot = this.baseSnapshot;
  private foldedSeq = 0;
  private headSeq = 0;
  private log: SketchpadLogEntry[] = [];
  private logComplete = false;
  private pending: PendingEntry[] = [];
  private snapshot: SketchpadSnapshot = emptySketchpadSnapshot();
  private fragmentErrors: Record<string, string> = {};
  private lastError: string | undefined;

  private loading = true;
  private loadFailed = false;
  private inFlight = false;
  private submittedOpIds: ReadonlySet<string> = new Set();
  private polling = false;
  private retryAttempt = 0;
  private visible = true;
  private live = false;
  private lifecycle: "idle" | "running" | "stopped" = "idle";
  private flushTimer: ReturnType<typeof setTimeout> | undefined;
  private retryTimer: ReturnType<typeof setTimeout> | undefined;
  private pollTimer: ReturnType<typeof setInterval> | undefined;
  readonly store: StoreApi<SketchpadSyncState>;

  constructor(
    api: SketchpadApi,
    sketchpadId: string,
    opts: SketchpadSyncOptions = {},
  ) {
    this.api = api;
    this.sketchpadId = sketchpadId;
    this.now = opts.now ?? (() => Date.now());
    this.actorUser = opts.actorUser;
    this.flushDebounceMs = opts.flushDebounceMs ?? FLUSH_DEBOUNCE_MS;
    this.pollIntervalMs = opts.pollIntervalMs ?? POLL_INTERVAL_MS;
    this.pendingStorage = opts.pendingStorage;
    this.store = createStore(() => this.buildState());
  }

  getState(): SketchpadSyncState {
    return this.store.getState();
  }

  setActorUser(actorUser: SketchpadSyncOptions["actorUser"]): void {
    this.actorUser = actorUser;
  }

  async load(): Promise<void> {
    this.loading = true;
    this.emit();
    try {
      if (!this.pendingLoaded) {
        const stored =
          this.pendingStorage &&
          (await this.pendingStorage.storage.getItem(this.pendingStorage.key));
        if (stored) {
          const entries = sketchpadLogEntrySchema
            .omit({ seq: true })
            .array()
            .parse(JSON.parse(stored));
          this.pending = [
            ...this.pending,
            ...entries.filter((entry) => !this.hasOp(entry.opId)),
          ];
        }
        this.pendingLoaded = true;
      }
      const board = await this.api.get(this.sketchpadId);
      this.name = board.name;
      this.channelId = board.channelId;
      if (board.headSeq >= this.baseSeq) {
        this.baseSnapshot = board.snapshot;
        this.baseSeq = board.headSeq;
      }
      this.headSeq = Math.max(this.headSeq, board.headSeq);
      this.refreshLogComplete();
      if (!this.isCurrent()) await this.catchUp();
      this.loadFailed = false;
      this.lastError = undefined;
      this.retryAttempt = 0;
    } catch (error) {
      this.loadFailed = true;
      this.lastError = errorMessage(error);
    } finally {
      this.loading = false;
      this.recompute();
      if (!this.loadFailed && this.pending.length > 0) this.scheduleFlush();
    }
  }

  async loadFullLog(): Promise<void> {
    if (this.logComplete) return;
    try {
      let since = 0;
      for (let page = 0; page < CATCH_UP_PAGE_BUDGET; page++) {
        const result = await this.api.opsSince(
          this.sketchpadId,
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

  applyLocal(
    ops: SketchpadOp[],
    actor?: { kind: "user" | "agent"; taskId?: string },
    opIds?: string[],
  ): void {
    const kind = actor?.kind ?? "user";
    const identity: SketchpadActor =
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
      const pendingOp =
        op.type === "restore"
          ? { ...op, expectedSeq: this.headSeq + this.pending.length }
          : op;
      this.appendPending({ opId, op: pendingOp, actor: identity, createdAt });
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
    if (this.inFlight) return;
    const batch = leadingActorRun(this.pending);
    if (batch.length === 0) return;

    const first = batch[0];
    const input: SketchpadAppendOpsInput = {
      ops: batch.map((entry) => ({ opId: entry.opId, op: entry.op })),
      actor: { kind: first.actor.kind, taskId: first.actor.taskId },
    };

    this.inFlight = true;
    this.submittedOpIds = new Set([
      ...this.submittedOpIds,
      ...batch.map((entry) => entry.opId),
    ]);
    this.emit();
    try {
      const result = await this.api.appendOps(this.sketchpadId, input);
      this.promote(batch, result);
      this.retryAttempt = 0;
      this.lastError = undefined;
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
      this.submittedOpIds = new Set(
        this.pending
          .filter((entry) => this.submittedOpIds.has(entry.opId))
          .map((entry) => entry.opId),
      );
      this.recompute();
    }

    if (this.retryAttempt === 0 && this.pending.length > 0) {
      this.scheduleFlush();
    }
  }

  async poll(): Promise<void> {
    if (this.polling || this.loading) return;
    if (this.loadFailed) return this.load();
    this.polling = true;
    const previousLog = this.log;
    try {
      await this.catchUp();
      this.retryAttempt = 0;
      this.lastError = undefined;
      if (this.log !== previousLog) this.recompute();
      else this.emit();
    } catch (error) {
      this.lastError = errorMessage(error);
      this.emit();
    } finally {
      this.polling = false;
    }
  }

  start(): void {
    this.lifecycle = "running";
    this.restartPollTimer();
  }

  stop(): void {
    this.lifecycle = "stopped";
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

  setLive(live: boolean): void {
    if (this.live === live) return;
    this.live = live;
    this.restartPollTimer();
    void this.poll();
    this.emit();
  }

  ingestStreamEntry(entry: SketchpadLogEntry): void {
    this.headSeq = Math.max(this.headSeq, entry.seq);
    const previousLog = this.log;
    this.ingest([entry]);
    if (this.log === previousLog) return;
    this.recompute();
    if (!this.loading && !this.isCurrent()) void this.poll();
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

  async restoreTo(seq: number): Promise<void> {
    if (!this.logComplete) await this.loadFullLog();
    if (!this.logComplete) {
      this.lastError = "The full history is not loaded yet.";
      this.emit();
      return;
    }
    const upTo = this.log.filter((entry) => entry.seq <= seq);
    const target = foldOps(emptySketchpadSnapshot(), upTo);
    this.applyLocal([{ type: "restore", snapshot: target, toSeq: seq }]);
  }

  async undoLastOwnOp(): Promise<void> {
    if (this.pending.length > 0) await this.flush();
    if (this.pending.length > 0) return;
    if (!this.logComplete) await this.loadFullLog();
    if (!this.logComplete) return;
    let beforeSeq = this.headSeq + 1;
    for (const entry of this.log.toReversed()) {
      if (!this.isOwnEntry(entry) || entry.seq >= beforeSeq) continue;
      if (entry.op.type === "restore") {
        beforeSeq = entry.op.toSeq + 1;
      } else {
        const retained = this.log.filter(
          (candidate) =>
            candidate.seq < entry.seq || !this.isOwnEntry(candidate),
        );
        this.applyLocal([
          {
            type: "restore",
            snapshot: foldOps(emptySketchpadSnapshot(), retained),
            toSeq: entry.seq - 1,
          },
        ]);
        return;
      }
    }
  }

  private isOwnEntry(entry: SketchpadLogEntry): boolean {
    if (entry.actor.kind !== "user") return false;
    const userId = this.actorUser?.userId;
    return userId !== undefined && entry.actor.userId === userId;
  }

  private rejectsStateValue(op: SketchpadOp): boolean {
    if (op.type !== "set_state") return false;
    if (estimateJsonBytes(op.value) <= SKETCHPAD_MAX_STATE_VALUE_BYTES) {
      return false;
    }
    this.lastError = `The value for "${op.key}" is too large to share on this board.`;
    return true;
  }

  private appendPending(entry: PendingEntry): void {
    const last = this.pending[this.pending.length - 1];
    const openLast =
      last !== undefined && !this.submittedOpIds.has(last.opId)
        ? last
        : undefined;
    const mergedEdits = openLast ? mergeFieldEdits(openLast, entry) : undefined;
    if (mergedEdits) {
      this.pending = [...this.pending.slice(0, -1), mergedEdits];
      return;
    }
    const mergeable =
      last !== undefined &&
      !this.submittedOpIds.has(last.opId) &&
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
    result: SketchpadAppendOpsResult,
  ): void {
    const seqByOpId = new Map(result.results.map((r) => [r.opId, r.seq]));
    const sent = new Set(batch.map((entry) => entry.opId));
    const promoted: SketchpadLogEntry[] = [];
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
    this.log = sortLog(
      dedupeByOpId([...(result.replayed ?? []), ...this.log, ...promoted]),
    );
    this.headSeq = Math.max(this.headSeq, result.headSeq, maxSeq);
    this.refreshLogComplete();

    if (!this.isCurrent()) void this.poll();
  }

  private ingest(entries: readonly SketchpadLogEntry[]): void {
    if (entries.length === 0) return;
    const known = new Set(this.log.map((entry) => entry.opId));
    const promotedOpIds = new Set<string>();
    const additions: SketchpadLogEntry[] = [];

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
      if (page > 0 && since >= this.headSeq) return;
      const result = await this.api.opsSince(
        this.sketchpadId,
        since,
        OPS_PAGE_LIMIT,
      );
      this.headSeq = Math.max(this.headSeq, result.headSeq);
      if (result.results.length === 0) return;
      this.ingest(result.results);
      if (this.contiguousHead() <= since) return;
    }
  }

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
    this.logComplete =
      this.log.length === this.headSeq &&
      this.log.every((entry, index) => entry.seq === index + 1);
  }

  private scheduleFlush(): void {
    if (this.flushTimer !== undefined) return;
    this.flushTimer = setTimeout(() => {
      this.flushTimer = undefined;
      void this.flush();
    }, this.flushDebounceMs);
  }

  private scheduleRetry(): void {
    if (this.lifecycle === "stopped") return;
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
    if (
      this.lifecycle !== "running" ||
      !this.visible ||
      (this.live && !this.loadFailed && this.isCurrent())
    ) {
      this.clearPollTimer();
      return;
    }
    if (this.pollTimer !== undefined) return;
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
    if (this.foldedBase !== this.baseSnapshot) {
      this.foldedBase = this.baseSnapshot;
      this.foldedSnapshot = this.baseSnapshot;
      this.foldedSeq = this.baseSeq;
    }
    const contiguousSeq = this.contiguousHead();
    this.foldedSnapshot = foldOps(
      this.foldedSnapshot,
      this.log.filter(
        (entry) => entry.seq > this.foldedSeq && entry.seq <= contiguousSeq,
      ),
    );
    this.foldedSeq = contiguousSeq;
    this.snapshot = foldOps(
      foldOps(
        this.foldedSnapshot,
        this.log.filter((entry) => entry.seq > contiguousSeq),
      ),
      this.pending,
    );
    this.emit();
  }

  private status(): SketchpadSyncStatus {
    if (this.loading) return "loading";
    if (this.retryAttempt > 0) return "offline";
    if (this.loadFailed) return "error";
    if (!this.isCurrent()) return "loading";
    if (this.inFlight || this.pending.length > 0) return "saving";
    return "synced";
  }

  private channelId: string | null = null;

  setName(name: string): void {
    if (this.name === name) return;
    this.name = name;
    this.emit();
  }

  private buildState(): SketchpadSyncState {
    return {
      sketchpadId: this.sketchpadId,
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
    if (
      this.lifecycle !== "stopped" &&
      this.pendingLoaded &&
      this.pendingStorage &&
      this.savedPending !== this.pending
    ) {
      this.savedPending = this.pending;
      void Promise.resolve(
        this.pendingStorage.storage.setItem(
          this.pendingStorage.key,
          JSON.stringify(this.pending),
        ),
      ).catch((error) => {
        this.lastError = errorMessage(error);
        this.store.setState(this.buildState(), true);
      });
    }
    this.restartPollTimer();
    this.store.setState(this.buildState(), true);
  }
}

export interface HistoryGroup {
  key: string;
  actor: SketchpadActor;
  minuteIso: string;
  firstSeq: number;
  lastSeq: number;
  descriptions: string[];
  fragmentIds: string[];
}

export function describeOp(
  entry: SketchpadLogEntry,
  before: SketchpadSnapshot,
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

export function groupLogEntries(
  log: SketchpadLogEntry[],
  base: SketchpadSnapshot,
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
    if (entry.op.type !== "set_state" && entry.op.type !== "edit_field") {
      snapshot = foldOps(snapshot, [entry]);
    }
  }

  return groups.reverse();
}

export function actorIdentity(actor: SketchpadActor): string {
  if (actor.kind === "agent") return `agent:${actor.taskId ?? "unknown"}`;
  return `user:${actor.userId ?? actor.userName ?? "me"}`;
}

function fragmentLabel(snapshot: SketchpadSnapshot, id: string): string {
  const fragment: SketchpadFragment | undefined = snapshot.fragments.find(
    (candidate) => candidate.id === id,
  );
  return fragment?.title ?? id;
}

function touchedFragmentId(op: SketchpadOp): string | undefined {
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
  if ("initialValue" in last.op || "initialValue" in entry.op) return undefined;
  if (actorIdentity(last.actor) !== actorIdentity(entry.actor))
    return undefined;

  const insert = [...(last.op.insert ?? []), ...(entry.op.insert ?? [])];
  const remove = [...(last.op.remove ?? []), ...(entry.op.remove ?? [])];
  if (
    insert.length > SKETCHPAD_FIELD_MAX_OP_ENTRIES ||
    remove.length > SKETCHPAD_FIELD_MAX_OP_ENTRIES
  ) {
    return undefined;
  }
  const op: SketchpadEditFieldOp = {
    type: "edit_field",
    key: last.op.key,
    kind: last.op.kind,
  };
  if (insert.length > 0) op.insert = insert;
  if (remove.length > 0) op.remove = remove;
  return { ...last, op };
}

function isGeometryUpdate(op: SketchpadOp): boolean {
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

function leadingActorRun(pending: readonly PendingEntry[]): PendingEntry[] {
  const first = pending[0];
  if (!first) return [];
  const identity = actorIdentity(first.actor);
  const run: PendingEntry[] = [];
  for (const entry of pending) {
    if (actorIdentity(entry.actor) !== identity) break;
    if (
      run.length > 0 &&
      (first.op.type === "restore" || entry.op.type === "restore")
    )
      break;
    if (entry.op.type === "edit_field" || first.op.type === "edit_field") {
      if (
        entry.op.type !== "edit_field" ||
        first.op.type !== "edit_field" ||
        entry.op.key !== first.op.key
      )
        break;
    }
    run.push(entry);
  }
  return run;
}

function sortLog(entries: SketchpadLogEntry[]): SketchpadLogEntry[] {
  return [...entries].sort((a, b) => a.seq - b.seq);
}

function dedupeByOpId(
  entries: readonly SketchpadLogEntry[],
): SketchpadLogEntry[] {
  const seen = new Set<string>();
  const out: SketchpadLogEntry[] = [];
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
