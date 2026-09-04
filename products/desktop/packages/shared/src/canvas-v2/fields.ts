import { z } from "zod";
import {
  CANVAS_V2_FIELD_ID_MAX_CHARS,
  CANVAS_V2_FIELD_KEY_MAX_CHARS,
  CANVAS_V2_FIELD_MAX_OP_ENTRIES,
  type CanvasV2FieldKind,
  type CanvasV2Op,
  canvasV2FieldKindSchema,
} from "./schemas";

export const CANVAS_V2_FIELD_MARK = "__field";

export const canvasV2FieldEntrySchema = z.object({
  k: z.string().min(1).max(CANVAS_V2_FIELD_KEY_MAX_CHARS),
  v: z.unknown(),
});
export type CanvasV2FieldEntry = z.infer<typeof canvasV2FieldEntrySchema>;

export const canvasV2FieldSchema = z.object({
  [CANVAS_V2_FIELD_MARK]: canvasV2FieldKindSchema,
  entries: z
    .record(
      z.string().max(CANVAS_V2_FIELD_ID_MAX_CHARS),
      canvasV2FieldEntrySchema,
    )
    .default({}),
  removed: z.array(z.string().max(CANVAS_V2_FIELD_ID_MAX_CHARS)).default([]),
});
export type CanvasV2Field = z.infer<typeof canvasV2FieldSchema>;

export type CanvasV2EditFieldOp = Extract<CanvasV2Op, { type: "edit_field" }>;
export type CanvasV2FieldInsert = NonNullable<CanvasV2EditFieldOp["insert"]>;

export interface CanvasV2FieldRow {
  id: string;
  entry: CanvasV2FieldEntry;
}

export function emptyField(kind: CanvasV2FieldKind): CanvasV2Field {
  return { [CANVAS_V2_FIELD_MARK]: kind, entries: {}, removed: [] };
}

export function isField(value: unknown): value is CanvasV2Field {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Partial<CanvasV2Field>;
  const kind = candidate[CANVAS_V2_FIELD_MARK];
  if (kind !== "text" && kind !== "list") return false;
  const entries = candidate.entries;
  if (typeof entries !== "object" || entries === null) return false;
  return !Array.isArray(entries) && Array.isArray(candidate.removed);
}

export function isFieldEntry(value: unknown): value is CanvasV2FieldEntry {
  if (typeof value !== "object" || value === null) return false;
  const entry = value as Partial<CanvasV2FieldEntry>;
  return (
    typeof entry.k === "string" &&
    entry.k.length > 0 &&
    entry.k.length <= CANVAS_V2_FIELD_KEY_MAX_CHARS &&
    "v" in entry
  );
}

export function fieldOrder(field: CanvasV2Field): CanvasV2FieldRow[] {
  const rows: CanvasV2FieldRow[] = [];
  for (const id of Object.keys(field.entries)) {
    const entry = field.entries[id];
    if (isFieldEntry(entry)) rows.push({ id, entry });
  }
  rows.sort((a, b) => {
    if (a.entry.k !== b.entry.k) return a.entry.k < b.entry.k ? -1 : 1;
    if (a.id === b.id) return 0;
    return a.id < b.id ? -1 : 1;
  });
  return rows;
}

/** `ids[i]` is the id of the entry that holds `text[i]`. */
export function materializeText(field: CanvasV2Field): {
  text: string;
  ids: string[];
} {
  const parts: string[] = [];
  const ids: string[] = [];
  for (const row of fieldOrder(field)) {
    const value = row.entry.v;
    if (typeof value !== "string" || value.length === 0) continue;
    parts.push(value);
    for (let i = 0; i < value.length; i++) ids.push(row.id);
  }
  return { text: parts.join(""), ids };
}

export function materializeList<T>(
  field: CanvasV2Field,
): { id: string; value: T }[] {
  return fieldOrder(field).map((row) => ({
    id: row.id,
    value: row.entry.v as T,
  }));
}

export function newEntryId(clientId: string, counter: number): string {
  return `${clientId}-${counter.toString(36)}`;
}

/** Digits in ASCII order, so a plain `<` on two keys agrees with their value. */
const KEY_DIGITS =
  "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz";
const KEY_ZERO = `a${KEY_DIGITS[0]}`;
const KEY_SMALLEST = `A${KEY_DIGITS[0].repeat(26)}`;
const KEY_JITTER_LENGTH = 2;

/**
 * A key that sorts after `a` and before `b`. The head of the integer part
 * carries the length of that part, so a key at the end of a long text stays
 * short. Every key ends with random digits, so two people who type in the same
 * gap get different keys and their characters do not interleave.
 */
export function keyBetween(a: string | null, b: string | null): string {
  return withJitter(keyBase(a, b), b);
}

function withJitter(key: string, upper: string | null): string {
  let jitter = "";
  for (let i = 0; i < KEY_JITTER_LENGTH; i++) {
    const index = 1 + Math.floor(Math.random() * (KEY_DIGITS.length - 1));
    jitter += KEY_DIGITS[index];
  }
  const candidate = key + jitter;
  if (upper !== null && candidate >= upper) return key;
  return candidate;
}

function keyBase(a: string | null, b: string | null): string {
  if (a === null) {
    if (b === null) return KEY_ZERO;
    const below = splitKey(b);
    if (below.int === KEY_SMALLEST) return below.int + midpoint("", below.frac);
    if (below.int < b) return below.int;
    return decrementInteger(below.int) ?? below.int + midpoint("", below.frac);
  }
  const above = splitKey(a);
  if (b === null) {
    return (
      incrementInteger(above.int) ?? above.int + midpoint(above.frac, null)
    );
  }
  const below = splitKey(b);
  if (above.int === below.int) {
    return above.int + midpoint(above.frac, below.frac);
  }
  const next = incrementInteger(above.int);
  if (next !== null && next < b) return next;
  return above.int + midpoint(above.frac, null);
}

/** `count` keys in order between the two neighbors, split in halves so a long paste stays short. */
function keysBetween(
  a: string | null,
  b: string | null,
  count: number,
): string[] {
  if (count <= 0) return [];
  if (count === 1) return [keyBetween(a, b)];
  if (b === null) {
    const keys: string[] = [];
    let last = a;
    for (let i = 0; i < count; i++) {
      last = keyBetween(last, null);
      keys.push(last);
    }
    return keys;
  }
  const half = Math.floor(count / 2);
  const middle = keyBetween(a, b);
  return [
    ...keysBetween(a, middle, half),
    middle,
    ...keysBetween(middle, b, count - half - 1),
  ];
}

function splitKey(key: string): { int: string; frac: string } {
  const length = integerLength(key.slice(0, 1));
  if (length === 0 || length > key.length) return { int: key, frac: "" };
  return { int: key.slice(0, length), frac: key.slice(length) };
}

function integerLength(head: string): number {
  if (head >= "a" && head <= "z") return head.charCodeAt(0) - 97 + 2;
  if (head >= "A" && head <= "Z") return 90 - head.charCodeAt(0) + 2;
  return 0;
}

function incrementInteger(value: string): string | null {
  const head = value.slice(0, 1);
  const digits = value.slice(1).split("");
  let carry = true;
  for (let i = digits.length - 1; carry && i >= 0; i--) {
    const next = digitIndex(digits[i]) + 1;
    carry = next === KEY_DIGITS.length;
    digits[i] = carry ? KEY_DIGITS[0] : KEY_DIGITS[next];
  }
  if (!carry) return head + digits.join("");
  if (head === "Z") return KEY_ZERO;
  if (head === "z") return null;
  const nextHead = String.fromCharCode(head.charCodeAt(0) + 1);
  if (nextHead > "a") digits.push(KEY_DIGITS[0]);
  else digits.pop();
  return nextHead + digits.join("");
}

function decrementInteger(value: string): string | null {
  const head = value.slice(0, 1);
  const last = KEY_DIGITS[KEY_DIGITS.length - 1];
  const digits = value.slice(1).split("");
  let borrow = true;
  for (let i = digits.length - 1; borrow && i >= 0; i--) {
    const next = digitIndex(digits[i]) - 1;
    borrow = next < 0;
    digits[i] = borrow ? last : KEY_DIGITS[next];
  }
  if (!borrow) return head + digits.join("");
  if (head === "a") return `Z${last}`;
  if (head === "A") return null;
  const prevHead = String.fromCharCode(head.charCodeAt(0) - 1);
  if (prevHead < "Z") digits.push(last);
  else digits.pop();
  return prevHead + digits.join("");
}

/** A fractional digit string strictly between `a` and `b`, never ending in the lowest digit. */
function midpoint(a: string, b: string | null): string {
  if (b !== null && b !== "") {
    let common = 0;
    while (common < b.length && (a[common] ?? KEY_DIGITS[0]) === b[common]) {
      common++;
    }
    if (common > 0) {
      return b.slice(0, common) + midpoint(a.slice(common), b.slice(common));
    }
  }
  const low = a === "" ? 0 : digitIndex(a.slice(0, 1));
  const high =
    b === null || b === "" ? KEY_DIGITS.length : digitIndex(b.slice(0, 1));
  if (high - low > 1) return KEY_DIGITS[Math.round(0.5 * (low + high))];
  if (b !== null && b.length > 1) return b.slice(0, 1);
  return KEY_DIGITS[low] + midpoint(a.slice(1), null);
}

function digitIndex(digit: string): number {
  return Math.max(0, KEY_DIGITS.indexOf(digit));
}

export interface CanvasV2DiffTextInput {
  base: string;
  baseIds: string[];
  next: string;
  field: CanvasV2Field;
  key: string;
  clientId: string;
  counterStart: number;
}

export interface CanvasV2DiffTextResult {
  ops: CanvasV2Op[];
  counterEnd: number;
}

/**
 * The ops that turn `base` into `next`. It removes only the ids of the
 * characters that changed, so a change by somebody else survives.
 */
export function diffTextToOps(
  input: CanvasV2DiffTextInput,
): CanvasV2DiffTextResult {
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
  const insert: CanvasV2FieldInsert = added.map((value, index) => ({
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
  kind: CanvasV2FieldKind,
  insert: CanvasV2FieldInsert,
  remove: string[],
): CanvasV2Op[] {
  const size = CANVAS_V2_FIELD_MAX_OP_ENTRIES;
  const chunks = Math.max(
    Math.ceil(insert.length / size),
    Math.ceil(remove.length / size),
  );
  const ops: CanvasV2Op[] = [];
  for (let i = 0; i < chunks; i++) {
    const insertChunk = insert.slice(i * size, (i + 1) * size);
    const removeChunk = remove.slice(i * size, (i + 1) * size);
    if (insertChunk.length === 0 && removeChunk.length === 0) continue;
    const op: CanvasV2EditFieldOp = { type: "edit_field", key, kind };
    if (insertChunk.length > 0) op.insert = insertChunk;
    if (removeChunk.length > 0) op.remove = removeChunk;
    ops.push(op);
  }
  return ops;
}

/** The longest equal start and end of the two texts, cut on a character boundary. */
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

/** The sort key of the nearest id that the field still holds, in one direction. */
function neighborKey(
  field: CanvasV2Field,
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
