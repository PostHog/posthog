import { z } from "zod";

export const SKETCHPAD_FRAGMENT_DEFAULT_WIDTH = 360;
export const SKETCHPAD_FRAGMENT_DEFAULT_HEIGHT = 240;
export const SKETCHPAD_MAX_STATE_VALUE_BYTES = 64 * 1024;
export const SKETCHPAD_MAX_OPS_PER_BATCH = 1000;

export const SKETCHPAD_FIELD_MAX_ENTRIES = 20_000;
export const SKETCHPAD_FIELD_MAX_REMOVED = 20_000;
export const SKETCHPAD_FIELD_MAX_OP_ENTRIES = 2_000;
export const SKETCHPAD_FIELD_ID_MAX_CHARS = 64;
export const SKETCHPAD_FIELD_KEY_MAX_CHARS = 64;

export const sketchpadFieldKindSchema = z.enum(["text", "list"]);
export type SketchpadFieldKind = z.infer<typeof sketchpadFieldKindSchema>;

export const sketchpadFragmentSchema = z.object({
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
  z: z.number().int().safe().default(0),
  code: z.string().min(1).max(200_000),
  codeVersion: z.number().int().default(1),
  surface: z.enum(["card", "plain"]).default("card"),
  hidden: z.boolean().default(false),
});
export type SketchpadFragment = z.infer<typeof sketchpadFragmentSchema>;

const RESERVED_STATE_KEYS = new Set(["__proto__", "constructor", "prototype"]);

export const SKETCHPAD_STATE_KEY_MAX_CHARS = 128;

export const sketchpadStateKeySchema = z
  .string()
  .min(1)
  .max(SKETCHPAD_STATE_KEY_MAX_CHARS)
  .refine((key) => !RESERVED_STATE_KEYS.has(key), {
    message: "That state key is reserved",
  });

export function isReservedStateKey(key: string): boolean {
  return RESERVED_STATE_KEYS.has(key);
}

export const sketchpadSnapshotSchema = z.object({
  schemaVersion: z.literal(1),
  fragments: z.array(sketchpadFragmentSchema).default([]),
  state: z.record(sketchpadStateKeySchema, z.unknown()).default({}),
});
export type SketchpadSnapshot = z.infer<typeof sketchpadSnapshotSchema>;

export const sketchpadFragmentPatchSchema = sketchpadFragmentSchema
  .omit({ id: true })
  .extend({
    z: sketchpadFragmentSchema.shape.z.removeDefault(),
    surface: sketchpadFragmentSchema.shape.surface.removeDefault(),
    hidden: sketchpadFragmentSchema.shape.hidden.removeDefault(),
    codeVersion: sketchpadFragmentSchema.shape.codeVersion.removeDefault(),
  })
  .partial();
export type SketchpadFragmentPatch = z.infer<
  typeof sketchpadFragmentPatchSchema
>;

export const sketchpadOpSchema = z.discriminatedUnion("type", [
  z.object({
    type: z.literal("add_fragment"),
    fragment: sketchpadFragmentSchema,
  }),
  z.object({
    type: z.literal("update_fragment"),
    id: z.string(),
    patch: sketchpadFragmentPatchSchema,
  }),
  z.object({ type: z.literal("remove_fragment"), id: z.string() }),
  z.object({ type: z.literal("bring_to_front"), id: z.string() }),
  z.object({
    type: z.literal("set_state"),
    key: sketchpadStateKeySchema,
    value: z.unknown(),
  }),
  z.object({
    type: z.literal("edit_field"),
    key: sketchpadStateKeySchema,
    kind: sketchpadFieldKindSchema,
    initialValue: z.unknown().optional(),
    insert: z
      .array(
        z.object({
          id: z.string().max(SKETCHPAD_FIELD_ID_MAX_CHARS),
          k: z.string().min(1).max(SKETCHPAD_FIELD_KEY_MAX_CHARS),
          v: z.unknown(),
        }),
      )
      .max(SKETCHPAD_FIELD_MAX_OP_ENTRIES)
      .optional(),
    remove: z
      .array(z.string().max(SKETCHPAD_FIELD_ID_MAX_CHARS))
      .max(SKETCHPAD_FIELD_MAX_OP_ENTRIES)
      .optional(),
  }),
  z.object({
    type: z.literal("restore"),
    snapshot: sketchpadSnapshotSchema,
    toSeq: z.number().int(),
    expectedSeq: z.number().int().min(0).optional(),
  }),
]);
export type SketchpadOp = z.infer<typeof sketchpadOpSchema>;
export type SketchpadOpType = SketchpadOp["type"];

export const sketchpadActorKindSchema = z.enum(["user", "agent"]);
export type SketchpadActorKind = z.infer<typeof sketchpadActorKindSchema>;

export const sketchpadUserSchema = z.object({
  userId: z.number().optional(),
  userUuid: z.string().optional(),
  userName: z.string().optional(),
  userEmail: z.string().optional(),
});

export const sketchpadActorSchema = sketchpadUserSchema.extend({
  kind: sketchpadActorKindSchema,
  taskId: z.string().optional(),
});
export type SketchpadActor = z.infer<typeof sketchpadActorSchema>;

export const sketchpadLogEntrySchema = z.object({
  seq: z.number().int(),
  opId: z.string(),
  actor: sketchpadActorSchema,
  createdAt: z.string(),
  op: sketchpadOpSchema,
});
export type SketchpadLogEntry = z.infer<typeof sketchpadLogEntrySchema>;

export const sketchpadSchema = z.object({
  id: z.string(),
  name: z.string().min(1).max(120),
  channelId: z.string(),
  createdAt: z.string(),
  updatedAt: z.string(),
  createdBy: sketchpadActorSchema.optional(),
  headSeq: z.number().int(),
  historyStartSeq: z.number().int(),
  historySnapshot: sketchpadSnapshotSchema,
  snapshot: sketchpadSnapshotSchema,
});
export type Sketchpad = z.infer<typeof sketchpadSchema>;

export const sketchpadSummarySchema = z.object({
  id: z.string(),
  name: z.string(),
  channelId: z.string(),
  createdAt: z.string(),
  updatedAt: z.string(),
  fragmentCount: z.number().int(),
  headSeq: z.number().int(),
  pinned: z.boolean().default(false),
  createdBy: sketchpadActorSchema.optional(),
  lastActor: sketchpadActorSchema.optional(),
  preview: z
    .array(
      z.object({
        x: z.number(),
        y: z.number(),
        w: z.number(),
        h: z.number(),
      }),
    )
    .default([]),
});
export type SketchpadSummary = z.infer<typeof sketchpadSummarySchema>;

export const sketchpadAppendOpsInputSchema = z.object({
  baseSeq: z.number().int().nonnegative(),
  ops: z.array(z.object({ opId: z.string().min(1), op: sketchpadOpSchema })),
  actor: z.object({
    kind: sketchpadActorKindSchema,
    taskId: z.string().optional(),
  }),
});
export type SketchpadAppendOpsInput = z.infer<
  typeof sketchpadAppendOpsInputSchema
>;

export const sketchpadAppendOpsResultSchema = z.object({
  results: z.array(z.object({ opId: z.string(), seq: z.number().int() })),
  replayed: z.array(sketchpadLogEntrySchema).optional(),
  headSeq: z.number().int(),
});
export type SketchpadAppendOpsResult = z.infer<
  typeof sketchpadAppendOpsResultSchema
>;

export const sketchpadOpsPageSchema = z.object({
  results: z.array(sketchpadLogEntrySchema),
  headSeq: z.number().int(),
  historyStartSeq: z.number().int(),
  historySnapshot: sketchpadSnapshotSchema,
});
export type SketchpadOpsPage = z.infer<typeof sketchpadOpsPageSchema>;

export const sketchpadCacheSchema = z
  .object({
    sketchpadId: z.string().min(1),
    name: z.string(),
    headSeq: z.number().int(),
    sources: z.array(sketchpadFragmentSchema.shape.code),
    snapshot: sketchpadSnapshotSchema.extend({
      fragments: z.array(
        sketchpadFragmentSchema.omit({ code: true }).extend({
          source: z.number().int().nonnegative(),
        }),
      ),
    }),
  })
  .refine(({ snapshot, sources }) =>
    snapshot.fragments.every(({ source }) => source < sources.length),
  );
export type SketchpadCachePayload = z.infer<typeof sketchpadCacheSchema>;

export function createSketchpadCache(
  input: Pick<Sketchpad, "name" | "headSeq" | "snapshot"> & {
    sketchpadId: string;
  },
): SketchpadCachePayload {
  const sources = new Map<string, number>();
  const fragments = input.snapshot.fragments.map(({ code, ...fragment }) => {
    let source = sources.get(code);
    if (source === undefined) {
      source = sources.size;
      sources.set(code, source);
    }
    return { ...fragment, source };
  });
  return {
    ...input,
    sources: [...sources.keys()],
    snapshot: { ...input.snapshot, fragments },
  };
}

export function emptySketchpadSnapshot(): SketchpadSnapshot {
  return { schemaVersion: 1, fragments: [], state: {} };
}
