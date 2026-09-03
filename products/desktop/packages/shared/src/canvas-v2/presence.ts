import { z } from "zod";
import { canvasV2ViewportSchema } from "./protocol";
import { canvasV2LogEntrySchema } from "./schemas";

/** A person leaves the board when no ping arrives inside this window. */
export const CANVAS_V2_PRESENCE_STALE_MS = 10_000;
/** The shortest gap between two pings while the pointer moves. */
export const CANVAS_V2_PRESENCE_INTERVAL_MS = 100;
export const CANVAS_V2_PRESENCE_MAX_SELECTED_IDS = 50;

export const canvasV2PresencePointSchema = z.object({
  x: z.number(),
  y: z.number(),
});
export type CanvasV2PresencePoint = z.infer<typeof canvasV2PresencePointSchema>;

/** What this client sends. The server takes the person from the request. */
export const canvasV2PresenceInputSchema = z.object({
  clientId: z.string().min(1).max(64),
  /** Board world units, or null when the pointer is off the board. */
  cursor: canvasV2PresencePointSchema.nullable(),
  viewport: canvasV2ViewportSchema.nullable(),
  selectedIds: z
    .array(z.string().max(64))
    .max(CANVAS_V2_PRESENCE_MAX_SELECTED_IDS),
});
export type CanvasV2PresenceInput = z.infer<typeof canvasV2PresenceInputSchema>;

/** What the stream sends back: one client's ping plus who it belongs to. */
export const canvasV2PresenceSchema = canvasV2PresenceInputSchema.extend({
  userId: z.number().optional(),
  userName: z.string().optional(),
});
export type CanvasV2Presence = z.infer<typeof canvasV2PresenceSchema>;

/** One frame of the board stream, as the renderer receives it. */
export const canvasV2StreamEventSchema = z.discriminatedUnion("type", [
  z.object({ type: z.literal("op"), entry: canvasV2LogEntrySchema }),
  z.object({ type: z.literal("presence"), presence: canvasV2PresenceSchema }),
  z.object({ type: z.literal("reload"), since: z.number().int() }),
  z.object({ type: z.literal("live"), live: z.boolean() }),
  z.object({ type: z.literal("error"), message: z.string().max(500) }),
]);
export type CanvasV2StreamEvent = z.infer<typeof canvasV2StreamEventSchema>;
