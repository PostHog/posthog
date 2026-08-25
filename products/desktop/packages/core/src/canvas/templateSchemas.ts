import { z } from "zod";

// A starter chip shown in an empty chat: `label` is the short text on the chip
// (often the capability under test), `prompt` is dropped into the composer.
export const canvasSuggestionSchema = z.object({
  label: z.string(),
  prompt: z.string(),
});
export type CanvasSuggestion = z.infer<typeof canvasSuggestionSchema>;

// What the create-picker needs to list templates (no heavy system prompt).
export const canvasTemplateSummarySchema = z.object({
  id: z.string(),
  name: z.string(),
  description: z.string(),
  builtIn: z.boolean(),
  suggestions: z.array(canvasSuggestionSchema),
});
export type CanvasTemplateSummary = z.infer<typeof canvasTemplateSummarySchema>;
