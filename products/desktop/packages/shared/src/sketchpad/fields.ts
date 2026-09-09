import { z } from "zod";
import {
  SKETCHPAD_FIELD_ID_MAX_CHARS,
  SKETCHPAD_FIELD_KEY_MAX_CHARS,
  type SketchpadFieldKind,
  type SketchpadOp,
  sketchpadFieldKindSchema,
} from "./schemas";

export const SKETCHPAD_FIELD_MARK = "__field";

export const sketchpadFieldEntrySchema = z.object({
  k: z.string().min(1).max(SKETCHPAD_FIELD_KEY_MAX_CHARS),
  v: z.unknown(),
});
export type SketchpadFieldEntry = z.infer<typeof sketchpadFieldEntrySchema>;

export const sketchpadFieldSchema = z.object({
  [SKETCHPAD_FIELD_MARK]: sketchpadFieldKindSchema,
  entries: z
    .record(
      z.string().max(SKETCHPAD_FIELD_ID_MAX_CHARS),
      sketchpadFieldEntrySchema,
    )
    .default({}),
  removed: z.array(z.string().max(SKETCHPAD_FIELD_ID_MAX_CHARS)).default([]),
});
export type SketchpadField = z.infer<typeof sketchpadFieldSchema>;

export type SketchpadEditFieldOp = Extract<SketchpadOp, { type: "edit_field" }>;
export type SketchpadFieldInsert = NonNullable<SketchpadEditFieldOp["insert"]>;

export interface SketchpadFieldRow {
  id: string;
  entry: SketchpadFieldEntry;
}

export function emptyField(kind: SketchpadFieldKind): SketchpadField {
  return { [SKETCHPAD_FIELD_MARK]: kind, entries: {}, removed: [] };
}

export function isField(value: unknown): value is SketchpadField {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Partial<SketchpadField>;
  const kind = candidate[SKETCHPAD_FIELD_MARK];
  if (kind !== "text" && kind !== "list") return false;
  const entries = candidate.entries;
  if (typeof entries !== "object" || entries === null) return false;
  return !Array.isArray(entries) && Array.isArray(candidate.removed);
}

export function isFieldEntry(value: unknown): value is SketchpadFieldEntry {
  if (typeof value !== "object" || value === null) return false;
  const entry = value as Partial<SketchpadFieldEntry>;
  return (
    typeof entry.k === "string" &&
    entry.k.length > 0 &&
    entry.k.length <= SKETCHPAD_FIELD_KEY_MAX_CHARS &&
    "v" in entry
  );
}

export function fieldOrder(field: SketchpadField): SketchpadFieldRow[] {
  const rows: SketchpadFieldRow[] = [];
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

export function materializeText(field: SketchpadField): {
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
  field: SketchpadField,
): { id: string; value: T }[] {
  return fieldOrder(field).map((row) => ({
    id: row.id,
    value: row.entry.v as T,
  }));
}

export function newEntryId(clientId: string, counter: number): string {
  return `${clientId}-${counter.toString(36)}`;
}
