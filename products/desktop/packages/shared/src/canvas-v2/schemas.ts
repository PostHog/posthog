import { z } from "zod";

export const CANVAS_V2_FRAGMENT_DEFAULT_WIDTH = 360;
export const CANVAS_V2_FRAGMENT_DEFAULT_HEIGHT = 240;
export const CANVAS_V2_MAX_STATE_VALUE_BYTES = 64 * 1024;

export const canvasV2FragmentSchema = z.object({
  id: z
    .string()
    .min(1)
    .max(64)
    .regex(/^[a-z0-9][a-z0-9-_]*$/),
  title: z.string().max(120).optional(),
  x: z.number(),
  y: z.number(),
  w: z.number().min(80).max(4000),
  h: z.number().min(60).max(4000),
  z: z.number().int().default(0),
  code: z.string().min(1).max(200_000),
  codeVersion: z.number().int().default(1),
});
export type CanvasV2Fragment = z.infer<typeof canvasV2FragmentSchema>;

export const canvasV2SnapshotSchema = z.object({
  schemaVersion: z.literal(1),
  fragments: z.array(canvasV2FragmentSchema).default([]),
  state: z.record(z.string().max(128), z.unknown()).default({}),
});
export type CanvasV2Snapshot = z.infer<typeof canvasV2SnapshotSchema>;

export const canvasV2FragmentPatchSchema = canvasV2FragmentSchema
  .omit({ id: true })
  .partial();
export type CanvasV2FragmentPatch = z.infer<typeof canvasV2FragmentPatchSchema>;

export const canvasV2OpSchema = z.discriminatedUnion("type", [
  z.object({
    type: z.literal("add_fragment"),
    fragment: canvasV2FragmentSchema,
  }),
  z.object({
    type: z.literal("update_fragment"),
    id: z.string(),
    patch: canvasV2FragmentPatchSchema,
  }),
  z.object({ type: z.literal("remove_fragment"), id: z.string() }),
  z.object({ type: z.literal("bring_to_front"), id: z.string() }),
  z.object({
    type: z.literal("set_state"),
    key: z.string().max(128),
    value: z.unknown(),
  }),
  z.object({
    type: z.literal("restore"),
    snapshot: canvasV2SnapshotSchema,
    toSeq: z.number().int(),
  }),
]);
export type CanvasV2Op = z.infer<typeof canvasV2OpSchema>;
export type CanvasV2OpType = CanvasV2Op["type"];

export const CANVAS_V2_OP_TYPES: readonly CanvasV2OpType[] = [
  "add_fragment",
  "update_fragment",
  "remove_fragment",
  "bring_to_front",
  "set_state",
  "restore",
];

export const canvasV2ActorKindSchema = z.enum(["user", "agent"]);
export type CanvasV2ActorKind = z.infer<typeof canvasV2ActorKindSchema>;

export const canvasV2ActorSchema = z.object({
  kind: canvasV2ActorKindSchema,
  userId: z.number().optional(),
  userName: z.string().optional(),
  taskId: z.string().optional(),
});
export type CanvasV2Actor = z.infer<typeof canvasV2ActorSchema>;

export const canvasV2LogEntrySchema = z.object({
  seq: z.number().int(),
  opId: z.string(),
  actor: canvasV2ActorSchema,
  createdAt: z.string(),
  op: canvasV2OpSchema,
});
export type CanvasV2LogEntry = z.infer<typeof canvasV2LogEntrySchema>;

export const canvasV2BoardSchema = z.object({
  id: z.string(),
  name: z.string().min(1).max(120),
  createdAt: z.string(),
  updatedAt: z.string(),
  createdBy: canvasV2ActorSchema.optional(),
  headSeq: z.number().int(),
  snapshot: canvasV2SnapshotSchema,
  snapshotSeq: z.number().int(),
  opsAfterSnapshot: z.array(canvasV2LogEntrySchema),
});
export type CanvasV2Board = z.infer<typeof canvasV2BoardSchema>;

export const canvasV2BoardSummarySchema = z.object({
  id: z.string(),
  name: z.string(),
  createdAt: z.string(),
  updatedAt: z.string(),
  fragmentCount: z.number().int(),
  headSeq: z.number().int(),
});
export type CanvasV2BoardSummary = z.infer<typeof canvasV2BoardSummarySchema>;

export interface CanvasV2OpDraft {
  opId: string;
  op: CanvasV2Op;
}

export interface CanvasV2AppendOpsInput {
  ops: CanvasV2OpDraft[];
  actor: { kind: CanvasV2ActorKind; taskId?: string };
  baseSeq: number;
  snapshot?: CanvasV2Snapshot;
}

export interface CanvasV2AppendOpsResult {
  results: { opId: string; seq: number }[];
  headSeq: number;
}

export interface CanvasV2OpsPage {
  results: CanvasV2LogEntry[];
  headSeq: number;
}

export interface CanvasV2CachePayload {
  boardId: string;
  name: string;
  headSeq: number;
  snapshot: CanvasV2Snapshot;
}

export function emptyCanvasV2Snapshot(): CanvasV2Snapshot {
  return { schemaVersion: 1, fragments: [], state: {} };
}
