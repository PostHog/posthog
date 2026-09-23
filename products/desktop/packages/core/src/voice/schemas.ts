import { z } from "zod";

const usageSchema = z.object({ seconds: z.number().nonnegative() });
export const liveVoiceEventSchema = z.discriminatedUnion("type", [
  z.object({
    type: z.literal("session.started"),
    session: z.object({ id: z.string() }),
  }),
  z.object({
    type: z.literal("session.closed"),
    usage: usageSchema.optional(),
  }),
  z.object({ type: z.literal("session.usage.updated"), usage: usageSchema }),
  z.object({ type: z.literal("error") }),
  z.object({
    type: z.enum([
      "session.input_transcript.delta",
      "session.output_transcript.delta",
    ]),
    event_id: z.string(),
    delta: z.string(),
    start_ms: z.number().nonnegative(),
    end_ms: z.number().nonnegative(),
  }),
  z.object({
    type: z.literal("session.delegation.created"),
    offset_ms: z.number().nonnegative(),
    delegation: z.object({ id: z.string(), target: z.literal("client") }),
  }),
]);

export type VoiceState =
  | "idle"
  | "connecting"
  | "connected"
  | "closing"
  | "error";
