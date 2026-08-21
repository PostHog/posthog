import { z } from "zod";

// Required fields are non-blank here rather than in the link builder, so a bad action fails at
// the boundary instead of being rebuilt into a button that does nothing when clicked. `label` is
// carried by the card and never reaches a link, so it is not declared.
const requiredField = z.string().trim().min(1);

/**
 * An action the agent offered the user, as the host will accept it: a typed verb
 * and the verb's own fields. There is deliberately no URL member — the host
 * builds every link itself with `buildActionUrl`.
 */
export const agentActionSchema = z.discriminatedUnion("kind", [
  z.object({
    kind: z.literal("compose"),
    prompt: requiredField,
    repo: z.string().trim().min(1).optional(),
  }),
  z.object({
    kind: z.literal("open_space"),
    channel_id: requiredField,
  }),
  z.object({
    kind: z.literal("open_canvas"),
    channel_id: requiredField,
    canvas_id: requiredField,
  }),
]);

export const openAgentActionInput = z.object({
  action: agentActionSchema,
});
