import { z } from "zod";
import { sketchpadViewportSchema } from "./protocol";
import {
  SKETCHPAD_FIELD_ID_MAX_CHARS,
  sketchpadLogEntrySchema,
} from "./schemas";

export const SKETCHPAD_PRESENCE_STALE_MS = 10_000;
export const SKETCHPAD_PRESENCE_INTERVAL_MS = 100;
export const SKETCHPAD_PRESENCE_MAX_SELECTED_IDS = 50;
export const SKETCHPAD_PRESENCE_MAX_CARETS = 4;

export const sketchpadPresenceCaretSchema = z.object({
  key: z.string().max(128),
  anchor: z.string().max(SKETCHPAD_FIELD_ID_MAX_CHARS).nullable(),
  focus: z.string().max(SKETCHPAD_FIELD_ID_MAX_CHARS).nullable(),
});
export type SketchpadPresenceCaret = z.infer<
  typeof sketchpadPresenceCaretSchema
>;

export const sketchpadPresencePointSchema = z.object({
  x: z.number(),
  y: z.number(),
});
export type SketchpadPresencePoint = z.infer<
  typeof sketchpadPresencePointSchema
>;

export const sketchpadPresenceInputSchema = z.object({
  clientId: z.string().min(1).max(64),
  cursor: sketchpadPresencePointSchema.nullable(),
  viewport: sketchpadViewportSchema.nullable(),
  selectedIds: z
    .array(z.string().max(64))
    .max(SKETCHPAD_PRESENCE_MAX_SELECTED_IDS),
  carets: z
    .array(sketchpadPresenceCaretSchema)
    .max(SKETCHPAD_PRESENCE_MAX_CARETS)
    .default([]),
});
export type SketchpadPresenceInput = z.infer<
  typeof sketchpadPresenceInputSchema
>;

export const sketchpadPresenceSchema = sketchpadPresenceInputSchema.extend({
  userId: z.number().optional(),
  userUuid: z.string().optional(),
  userName: z.string().optional(),
  userEmail: z.string().optional(),
});
export type SketchpadPresence = z.infer<typeof sketchpadPresenceSchema>;

export const sketchpadStreamEventSchema = z.discriminatedUnion("type", [
  z.object({ type: z.literal("op"), entry: sketchpadLogEntrySchema }),
  z.object({ type: z.literal("presence"), presence: sketchpadPresenceSchema }),
  z.object({ type: z.literal("reload"), since: z.number().int() }),
  z.object({ type: z.literal("live"), live: z.boolean() }),
  z.object({ type: z.literal("error"), message: z.string().max(500) }),
]);
export type SketchpadStreamEvent = z.infer<typeof sketchpadStreamEventSchema>;
