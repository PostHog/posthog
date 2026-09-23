import { z } from "zod";
import { canvasSourceProjectSchema } from "./dashboardSchemas";

export const publishProjectInput = z.object({
  id: z.string().min(1),
  project: canvasSourceProjectSchema,
  expectedCurrentVersionId: z.string().nullable(),
  prompt: z.string().optional(),
});
export type PublishProjectInput = z.infer<typeof publishProjectInput>;

export const publishProjectResultSchema = z.discriminatedUnion("status", [
  z.object({ status: z.literal("saved"), currentVersionId: z.string() }),
  z.object({
    status: z.literal("conflict"),
    currentVersionId: z.string().nullable(),
  }),
]);
export type PublishProjectResult = z.infer<typeof publishProjectResultSchema>;
