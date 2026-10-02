import { z } from "zod/v4";

export const contextSelectionResponseSchema = z
  .object({
    selection_id: z.string().max(128),
    context: z.string().max(8_000),
    mode: z.enum(["disabled", "control", "shadow", "treatment"]),
    reason: z.string().max(128),
  })
  .refine(
    (value) =>
      !value.context ||
      (value.mode === "treatment" && Boolean(value.selection_id)),
    {
      message: "Only a treatment selection may supply context",
    },
  );

export type ContextSelectionResponse = z.infer<
  typeof contextSelectionResponseSchema
>;
