import {
  canvasV2ActorKindSchema,
  canvasV2LogEntrySchema,
  canvasV2OpSchema,
  canvasV2PresenceInputSchema,
  canvasV2SnapshotSchema,
} from "@posthog/shared";
import { z } from "zod";

export const canvasV2BoardIdInput = z.object({ id: z.string().min(1) });

export const canvasV2SendPresenceInput = z.object({
  id: z.string().min(1),
  presence: canvasV2PresenceInputSchema,
});

export const canvasV2ChannelInput = z.object({
  channelId: z.string().min(1),
});

export const createCanvasV2BoardInput = z.object({
  channelId: z.string().min(1),
  name: z.string().min(1).max(120),
});

export const fileCanvasV2BoardInput = z.object({
  id: z.string().min(1),
  channelId: z.string().min(1),
});

export const renameCanvasV2BoardInput = z.object({
  id: z.string().min(1),
  name: z.string().min(1).max(120),
});

export const canvasV2OpsSinceInput = z.object({
  id: z.string().min(1),
  since: z.number().int().min(0),
  limit: z.number().int().min(1).max(1000).optional(),
});

export const canvasV2AppendOpsInputSchema = z.object({
  id: z.string().min(1),
  ops: z.array(z.object({ opId: z.string().min(1), op: canvasV2OpSchema })),
  actor: z.object({
    kind: canvasV2ActorKindSchema,
    taskId: z.string().optional(),
  }),
  baseSeq: z.number().int().min(0),
  snapshot: canvasV2SnapshotSchema.optional(),
});

export const canvasV2OpsPageSchema = z.object({
  results: z.array(canvasV2LogEntrySchema),
  headSeq: z.number().int(),
});

export const canvasV2AppendOpsResultSchema = z.object({
  results: z.array(z.object({ opId: z.string(), seq: z.number().int() })),
  headSeq: z.number().int(),
});
