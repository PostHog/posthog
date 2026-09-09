import { z } from "zod";
import {
  sketchpadPresenceCaretSchema,
  sketchpadViewportSchema,
} from "./protocol";
import { sketchpadLogEntrySchema, sketchpadUserSchema } from "./schemas";

export const SKETCHPAD_PRESENCE_STALE_MS = 10_000;
export const SKETCHPAD_PRESENCE_INTERVAL_MS = 100;
export const SKETCHPAD_PRESENCE_MAX_SELECTED_IDS = 50;
export const SKETCHPAD_PRESENCE_MAX_CARETS = 4;

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

export const sketchpadPresenceSchema = sketchpadPresenceInputSchema.extend(
  sketchpadUserSchema.shape,
);
export type SketchpadPresence = z.infer<typeof sketchpadPresenceSchema>;

export const sketchpadStreamEventSchema = z.discriminatedUnion("type", [
  z.object({ type: z.literal("op"), entry: sketchpadLogEntrySchema }),
  z.object({ type: z.literal("presence"), presence: sketchpadPresenceSchema }),
  z.object({ type: z.literal("reload"), since: z.number().int() }),
  z.object({ type: z.literal("live"), live: z.boolean() }),
  z.object({ type: z.literal("error"), message: z.string().max(500) }),
]);
export type SketchpadStreamEvent = z.infer<typeof sketchpadStreamEventSchema>;
