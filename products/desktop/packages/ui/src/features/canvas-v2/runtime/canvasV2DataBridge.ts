import {
  applyOp,
  CANVAS_V2_FIELD_MARK,
  CANVAS_V2_FIELD_MAX_ENTRIES,
  CANVAS_V2_FIELD_MAX_OP_ENTRIES,
  CANVAS_V2_FIELD_MAX_REMOVED,
  CANVAS_V2_MAX_STATE_VALUE_BYTES,
  type CanvasV2DataMethod,
  type CanvasV2Field,
  type CanvasV2FieldKind,
  type CanvasV2Op,
  type CanvasV2PresenceCaret,
  type CanvasV2Snapshot,
  diffTextToOps,
  emptyCanvasV2Snapshot,
  emptyField,
  estimateJsonBytes,
  fieldOrder,
  isField,
  keyBetween,
  materializeList,
  materializeText,
  newEntryId,
} from "@posthog/shared";
import { handleFreeformDataRequest } from "@posthog/ui/features/canvas/freeform/freeformDataBridge";
import {
  SHARED_FIELD_READ_ONLY_STATE,
  SHARED_TEXT_CHANGES_FULL,
  SHARED_TEXT_FULL,
} from "@posthog/ui/features/canvas-v2/canvasV2Copy";
import { fieldPlainValue } from "@posthog/ui/features/canvas-v2/runtime/canvasV2FieldMessages";
import type { QueryClient } from "@tanstack/react-query";

export interface CanvasV2DataBridgeContext {
  boardId: string;
  queryClient: QueryClient;
  getSnapshot: () => CanvasV2Snapshot;
  applyLocal: (ops: CanvasV2Op[], opIds?: string[]) => void;
  /** Where this person edits a field, for the next presence ping. */
  reportCaret: (caret: CanvasV2PresenceCaret | null) => void;
}

interface CanvasV2TextEditPayload {
  base?: unknown;
  baseIds?: unknown;
  next?: unknown;
  caret?: unknown;
}

interface CanvasV2ListEditPayload {
  insert?: unknown;
  remove?: unknown;
  update?: unknown;
}

interface BoardFieldMemory {
  /** Never restarts, so one client never writes an entry id twice. */
  counter: number;
  fields: Map<string, CanvasV2Field>;
}

// The board snapshot reaches this file through React, so it can be one
// keystroke behind. The last field this bridge built is merged into it, which
// is safe because the entries commute.
const boards = new Map<string, BoardFieldMemory>();

const BRIDGE_CLIENT_ID = globalThis.crypto.randomUUID().replace(/-/g, "");

const SEED_KEY_HEAD = "d";
const SEED_KEY_WIDTH = 4;
const SEED_KEY_DIGITS =
  "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz";

// Resolves a `ph.*` request from a board frame. Reads go through the existing
// freeform bridge (same cache, same host call); shared state is the board's own
// synced state, so it is served from the snapshot and written as an op.
export async function handleCanvasV2DataRequest(
  method: CanvasV2DataMethod,
  payload: unknown,
  ctx: CanvasV2DataBridgeContext,
): Promise<unknown> {
  switch (method) {
    case "query":
    case "loadInsight":
      // Neither case reads the dashboard context, so none is passed.
      return handleFreeformDataRequest(method, payload, ctx.queryClient);
    case "stateGet": {
      const key = readKey(payload, "ph.state.get(key) requires a key");
      return fieldPlainValue(ctx.getSnapshot().state[key] ?? null);
    }
    case "stateSet": {
      const key = readKey(payload, "ph.state.set(key, value) requires a key");
      if (isField(ctx.getSnapshot().state[key])) {
        throw new Error(SHARED_FIELD_READ_ONLY_STATE);
      }
      const raw = (payload as { value?: unknown }).value;
      const value = raw === undefined ? null : raw;
      if (estimateJsonBytes(value) > CANVAS_V2_MAX_STATE_VALUE_BYTES) {
        throw new Error(
          `ph.state.set(key, value) is limited to ${Math.floor(CANVAS_V2_MAX_STATE_VALUE_BYTES / 1024)} KB per value`,
        );
      }
      ctx.applyLocal([{ type: "set_state", key, value }]);
      return { ok: true };
    }
    case "stateList":
      return Object.entries(ctx.getSnapshot().state).map(([key, value]) => ({
        key,
        value: fieldPlainValue(value),
      }));
    case "stateEditText":
      return editText(payload, ctx);
    case "stateEditList":
      return editList(payload, ctx);
    default:
      throw new Error(`ph.${method} is not available on Canvases v2 yet`);
  }
}

function editText(
  payload: unknown,
  ctx: CanvasV2DataBridgeContext,
): { text: string; ids: string[] } {
  const key = readKey(payload, "ph.state.editText(key, edit) requires a key");
  const input = (payload ?? {}) as CanvasV2TextEditPayload;
  const memory = memoryOf(ctx.boardId);
  const field = readyField(ctx, key, "text");
  // One id per character, or the frame edited a text this field never held.
  const sent = {
    text: readString(input.base),
    ids: readStrings(input.baseIds),
  };
  const base =
    sent.ids.length === sent.text.length ? sent : materializeText(field);
  const diff = diffTextToOps({
    base: base.text,
    baseIds: base.ids,
    next: readString(input.next),
    field,
    key,
    clientId: BRIDGE_CLIENT_ID,
    counterStart: memory.counter,
  });
  refuseWhenFull(field, diff.ops);
  memory.counter = diff.counterEnd;
  const after = commit(ctx, key, field, diff.ops);
  const view = materializeText(after);
  ctx.reportCaret(caretOf(key, view.ids, input.caret));
  return view;
}

function editList(
  payload: unknown,
  ctx: CanvasV2DataBridgeContext,
): { items: { id: string; value: unknown }[] } {
  const key = readKey(payload, "ph.state.editList(key, edit) requires a key");
  const input = (payload ?? {}) as CanvasV2ListEditPayload;
  const field = readyField(ctx, key, "list");
  const ops = listOps(ctx, key, field, input);
  refuseWhenFull(field, ops);
  const after = commit(ctx, key, field, ops);
  return { items: materializeList(after) };
}

/** Turns the caret offsets the frame sent into the entry ids others can use. */
function caretOf(
  key: string,
  ids: string[],
  raw: unknown,
): CanvasV2PresenceCaret | null {
  if (typeof raw !== "object" || raw === null) return null;
  const caret = raw as { anchor?: unknown; focus?: unknown };
  return {
    key,
    anchor: idAt(ids, caret.anchor),
    focus: idAt(ids, caret.focus),
  };
}

function idAt(ids: string[], offset: unknown): string | null {
  if (typeof offset !== "number" || offset < 0) return null;
  return offset < ids.length ? ids[offset] : null;
}

function listOps(
  ctx: CanvasV2DataBridgeContext,
  key: string,
  field: CanvasV2Field,
  input: CanvasV2ListEditPayload,
): CanvasV2Op[] {
  const memory = memoryOf(ctx.boardId);
  const rows = fieldOrder(field);
  const insert: NonNullable<
    Extract<CanvasV2Op, { type: "edit_field" }>["insert"]
  > = [];

  for (const change of readRecords(input.update)) {
    const id = typeof change.id === "string" ? change.id : "";
    const entry = field.entries[id];
    if (entry === undefined) continue;
    insert.push({ id, k: entry.k, v: change.value });
  }

  for (const change of readRecords(input.insert)) {
    const anchor = typeof change.afterId === "string" ? change.afterId : null;
    const at =
      anchor === null ? -1 : rows.findIndex((row) => row.id === anchor);
    const after = anchor !== null && at === -1 ? rows.length - 1 : at;
    const left = after >= 0 ? rows[after].entry.k : null;
    const right = after + 1 < rows.length ? rows[after + 1].entry.k : null;
    const entry = { k: keyBetween(left, right), v: change.value };
    const id = newEntryId(BRIDGE_CLIENT_ID, memory.counter++);
    rows.splice(after + 1, 0, { id, entry });
    insert.push({ id, k: entry.k, v: change.value });
  }

  const remove = readStrings(input.remove);
  if (insert.length === 0 && remove.length === 0) return [];
  return [
    {
      type: "edit_field",
      key,
      kind: "list",
      insert: insert.slice(0, CANVAS_V2_FIELD_MAX_OP_ENTRIES),
      remove: remove.slice(0, CANVAS_V2_FIELD_MAX_OP_ENTRIES),
    },
  ];
}

/** Sends the ops to the board and answers from the field they produce. */
function commit(
  ctx: CanvasV2DataBridgeContext,
  key: string,
  field: CanvasV2Field,
  ops: CanvasV2Op[],
): CanvasV2Field {
  if (ops.length === 0) return field;
  const after = foldField(key, field, ops);
  memoryOf(ctx.boardId).fields.set(key, after);
  ctx.applyLocal(ops);
  return after;
}

function refuseWhenFull(field: CanvasV2Field, ops: CanvasV2Op[]): void {
  let inserted = 0;
  let removed = 0;
  for (const op of ops) {
    if (op.type !== "edit_field") continue;
    inserted += op.insert?.length ?? 0;
    removed += op.remove?.length ?? 0;
  }
  const live = Object.keys(field.entries).length;
  if (live + inserted > CANVAS_V2_FIELD_MAX_ENTRIES) {
    throw new Error(SHARED_TEXT_FULL);
  }
  if (field.removed.length + removed > CANVAS_V2_FIELD_MAX_REMOVED) {
    throw new Error(SHARED_TEXT_CHANGES_FULL);
  }
}

/** The field at `key`, seeded from a plain value the first time it is edited. */
function readyField(
  ctx: CanvasV2DataBridgeContext,
  key: string,
  kind: CanvasV2FieldKind,
): CanvasV2Field {
  const memory = memoryOf(ctx.boardId);
  const live = ctx.getSnapshot().state[key];
  if (!isField(live) && memory.fields.get(key) === undefined) {
    const ops = seedOps(key, kind, live);
    if (ops.length > 0) {
      const opIds = ops.map((_, index) =>
        index === 0 ? `seed:${key}` : `seed:${key}:${index}`,
      );
      const seeded = foldField(key, emptyField(kind), ops);
      memory.fields.set(key, seeded);
      ctx.applyLocal(ops, opIds);
      return seeded;
    }
  }
  const base = isField(live) ? live : emptyField(kind);
  const cached = memory.fields.get(key);
  const merged = cached === undefined ? base : mergeFields(base, cached);
  return merged[CANVAS_V2_FIELD_MARK] === kind ? merged : emptyField(kind);
}

/**
 * The one op that turns a plain value into a field. The op id is the same on
 * every client, so the server keeps the first and the seed happens once.
 */
function seedOps(
  key: string,
  kind: CanvasV2FieldKind,
  value: unknown,
): CanvasV2Op[] {
  const parts: unknown[] =
    kind === "text" && typeof value === "string"
      ? Array.from(value)
      : kind === "list" && Array.isArray(value)
        ? value
        : [];
  const entries = parts
    .slice(0, CANVAS_V2_FIELD_MAX_ENTRIES)
    .map((part, index) => ({
      id: newEntryId("seed", index),
      k: seedKey(index),
      v: part,
    }));
  const ops: CanvasV2Op[] = [];
  for (let at = 0; at < entries.length; at += CANVAS_V2_FIELD_MAX_OP_ENTRIES) {
    ops.push({
      type: "edit_field",
      key,
      kind,
      insert: entries.slice(at, at + CANVAS_V2_FIELD_MAX_OP_ENTRIES),
    });
  }
  return ops;
}

/** A sort key of one fixed width, so every client seeds the same order. */
function seedKey(index: number): string {
  let digits = "";
  let rest = index;
  for (let at = 0; at < SEED_KEY_WIDTH; at++) {
    digits = SEED_KEY_DIGITS[rest % SEED_KEY_DIGITS.length] + digits;
    rest = Math.floor(rest / SEED_KEY_DIGITS.length);
  }
  return SEED_KEY_HEAD + digits;
}

function foldField(
  key: string,
  field: CanvasV2Field,
  ops: CanvasV2Op[],
): CanvasV2Field {
  let carrier: CanvasV2Snapshot = {
    ...emptyCanvasV2Snapshot(),
    state: { [key]: field },
  };
  for (const op of ops) carrier = applyOp(carrier, op);
  const next = carrier.state[key];
  return isField(next) ? next : field;
}

function mergeFields(base: CanvasV2Field, extra: CanvasV2Field): CanvasV2Field {
  const removed = new Set([...base.removed, ...extra.removed]);
  const entries = { ...base.entries, ...extra.entries };
  for (const id of removed) delete entries[id];
  return {
    [CANVAS_V2_FIELD_MARK]: base[CANVAS_V2_FIELD_MARK],
    entries,
    removed: [...removed].slice(-CANVAS_V2_FIELD_MAX_REMOVED),
  };
}

function memoryOf(boardId: string): BoardFieldMemory {
  const found = boards.get(boardId);
  if (found !== undefined) return found;
  const memory: BoardFieldMemory = { counter: 0, fields: new Map() };
  boards.set(boardId, memory);
  return memory;
}

function readString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function readStrings(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string");
}

function readRecords(
  value: unknown,
): { id?: unknown; afterId?: unknown; value: unknown }[] {
  if (!Array.isArray(value)) return [];
  return value.filter(
    (item): item is { id?: unknown; afterId?: unknown; value: unknown } =>
      typeof item === "object" && item !== null,
  );
}

function readKey(payload: unknown, message: string): string {
  const key = (payload as { key?: unknown } | null)?.key;
  if (typeof key !== "string" || key.length === 0) throw new Error(message);
  return key;
}
