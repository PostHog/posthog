import {
  isFieldEntry,
  newEntryId,
  type SketchpadEditFieldOp,
  type SketchpadField,
  type SketchpadFieldInsert,
} from "./fields";
import { keysBetween } from "./orderKey";
import {
  SKETCHPAD_FIELD_MAX_OP_ENTRIES,
  type SketchpadFieldKind,
  type SketchpadOp,
} from "./schemas";

export interface SketchpadDiffTextInput {
  base: string;
  baseIds: string[];
  next: string;
  field: SketchpadField;
  key: string;
  clientId: string;
  counterStart: number;
}

export interface SketchpadDiffTextResult {
  ops: SketchpadOp[];
  counterEnd: number;
}

export function diffTextToOps(
  input: SketchpadDiffTextInput,
): SketchpadDiffTextResult {
  const { base, baseIds, next, field, key, clientId } = input;
  if (base === next) return { ops: [], counterEnd: input.counterStart };

  const bounds = commonBounds(base, next);
  const remove = uniqueIds(
    baseIds.slice(bounds.prefix, base.length - bounds.suffix),
  );
  const added = Array.from(
    next.slice(bounds.prefix, next.length - bounds.suffix),
  );

  const left = neighborKey(field, baseIds, bounds.prefix - 1, -1);
  const right = neighborKey(field, baseIds, base.length - bounds.suffix, 1);
  const keys = keysBetween(left, right, added.length);

  let counter = input.counterStart;
  const insert: SketchpadFieldInsert = added.map((value, index) => ({
    id: newEntryId(clientId, counter++),
    k: keys[index],
    v: value,
  }));

  return {
    ops: editFieldOps(key, "text", insert, remove),
    counterEnd: counter,
  };
}

function editFieldOps(
  key: string,
  kind: SketchpadFieldKind,
  insert: SketchpadFieldInsert,
  remove: string[],
): SketchpadOp[] {
  const size = SKETCHPAD_FIELD_MAX_OP_ENTRIES;
  const chunks = Math.max(
    Math.ceil(insert.length / size),
    Math.ceil(remove.length / size),
  );
  const ops: SketchpadOp[] = [];
  for (let i = 0; i < chunks; i++) {
    const insertChunk = insert.slice(i * size, (i + 1) * size);
    const removeChunk = remove.slice(i * size, (i + 1) * size);
    if (insertChunk.length === 0 && removeChunk.length === 0) continue;
    const op: SketchpadEditFieldOp = { type: "edit_field", key, kind };
    if (insertChunk.length > 0) op.insert = insertChunk;
    if (removeChunk.length > 0) op.remove = removeChunk;
    ops.push(op);
  }
  return ops;
}

function commonBounds(
  base: string,
  next: string,
): { prefix: number; suffix: number } {
  const shortest = Math.min(base.length, next.length);
  let prefix = 0;
  while (prefix < shortest && base[prefix] === next[prefix]) prefix++;
  if (prefix > 0 && isHighSurrogate(base.charCodeAt(prefix - 1))) prefix--;
  let suffix = 0;
  while (
    suffix < shortest - prefix &&
    base[base.length - 1 - suffix] === next[next.length - 1 - suffix]
  ) {
    suffix++;
  }
  if (suffix > 0 && isLowSurrogate(base.charCodeAt(base.length - suffix))) {
    suffix--;
  }
  return { prefix, suffix };
}

function isHighSurrogate(code: number): boolean {
  return code >= 0xd800 && code <= 0xdbff;
}

function isLowSurrogate(code: number): boolean {
  return code >= 0xdc00 && code <= 0xdfff;
}

function neighborKey(
  field: SketchpadField,
  ids: string[],
  from: number,
  step: number,
): string | null {
  for (let i = from; i >= 0 && i < ids.length; i += step) {
    const entry = field.entries[ids[i]];
    if (isFieldEntry(entry)) return entry.k;
  }
  return null;
}

function uniqueIds(ids: string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const id of ids) {
    if (seen.has(id)) continue;
    seen.add(id);
    out.push(id);
  }
  return out;
}
