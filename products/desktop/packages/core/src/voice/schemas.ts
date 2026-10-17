import { z } from "zod";

const usageSchema = z.object({ seconds: z.number().nonnegative() });
export const liveVoiceEventSchema = z.discriminatedUnion("type", [
  z.object({
    type: z.literal("session.started"),
    session: z.object({
      id: z.string(),
      delegation: z.object({ type: z.enum(["client", "responses"]) }).nullish(),
    }),
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
    type: z.literal("response.event"),
    delegation_id: z.string(),
    event: z.discriminatedUnion("type", [
      z.object({
        type: z.literal("response.created"),
        response: z.object({ id: z.string() }),
      }),
      z.object({
        type: z.literal("response.output_item.done"),
        item: z.object({
          type: z.literal("function_call"),
          call_id: z.string(),
          name: z.string(),
          arguments: z.string(),
        }),
      }),
      z.object({
        type: z.enum([
          "response.completed",
          "response.failed",
          "response.incomplete",
        ]),
        response: z.object({ id: z.string(), status: z.string() }),
      }),
    ]),
  }),
  z.object({
    type: z.literal("session.delegation.created"),
    offset_ms: z.number().nonnegative(),
    delegation: z.object({
      id: z.string(),
      target: z.enum(["client", "responses"]),
    }),
  }),
]);

export type VoiceErrorState = "error" | "microphone-error" | "service-error";

export type VoiceState =
  | "idle"
  | "connecting"
  | "connected"
  | "closing"
  | VoiceErrorState;

export function isVoiceErrorState(state: VoiceState): state is VoiceErrorState {
  return (
    state === "error" ||
    state === "microphone-error" ||
    state === "service-error"
  );
}

export const voiceAnswerArgumentsSchema = z.object({
  question_id: z.string().min(1),
  option_ids: z.array(z.string()).max(20),
  custom_answer: z.string().max(8000),
});

export const voiceTaskArgumentsSchema = z.object({
  text: z.string().trim().min(1).max(8000),
});

export interface VoiceToolCall {
  id: string;
  name: "answer_question" | "send_to_task";
  input: string;
  status: "running" | "completed" | "failed";
  result?: string;
}
