import {
  SKETCHPAD_FIELD_MAX_OP_ENTRIES,
  type SketchpadEditFieldOp,
  type SketchpadLogEntry,
  type SketchpadOp,
} from "@posthog/shared";
import { actorIdentity } from "./sketchpadHistory";

export type PendingEntry = Omit<SketchpadLogEntry, "seq">;
const GEOMETRY_KEYS: readonly string[] = ["x", "y", "w", "h"];

export function appendPending(
  pending: PendingEntry[],
  entry: PendingEntry,
  submittedOpIds: ReadonlySet<string>,
): PendingEntry[] {
  const last = pending.at(-1);
  const merged =
    last && !submittedOpIds.has(last.opId)
      ? (mergeFieldEdits(last, entry) ?? mergeGeometryUpdates(last, entry))
      : undefined;
  return merged ? [...pending.slice(0, -1), merged] : [...pending, entry];
}

function mergeGeometryUpdates(
  last: PendingEntry,
  entry: PendingEntry,
): PendingEntry | undefined {
  if (last.op.type !== "update_fragment" || entry.op.type !== "update_fragment")
    return undefined;
  if (
    last.op.id !== entry.op.id ||
    !isGeometryUpdate(last.op) ||
    !isGeometryUpdate(entry.op)
  )
    return undefined;
  if (actorIdentity(last.actor) !== actorIdentity(entry.actor))
    return undefined;
  return {
    ...last,
    op: { ...last.op, patch: { ...last.op.patch, ...entry.op.patch } },
  };
}

function canBatch(first: PendingEntry, entry: PendingEntry): boolean {
  if (actorIdentity(first.actor) !== actorIdentity(entry.actor)) return false;
  if (first.op.type === "restore" || entry.op.type === "restore") return false;
  if (first.op.type === "edit_field" || entry.op.type === "edit_field") {
    return (
      first.op.type === "edit_field" &&
      entry.op.type === "edit_field" &&
      first.op.key === entry.op.key
    );
  }
  return true;
}

export function leadingActorRun(
  pending: readonly PendingEntry[],
): PendingEntry[] {
  const first = pending[0];
  if (!first) return [];
  const end = pending.findIndex(
    (entry, index) => index > 0 && !canBatch(first, entry),
  );
  return pending.slice(0, end < 0 ? pending.length : end);
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
