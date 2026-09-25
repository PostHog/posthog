import { z } from "zod";

export const savedDraftSchema = z.object({
  text: z.string().max(100_000),
  taskId: z.string().optional(),
  photos: z
    .array(
      z.object({
        id: z.string(),
        uri: z.string(),
        name: z.string(),
        mimeType: z.string(),
        jpegBase64: z.string().optional(),
      }),
    )
    .max(3),
});

export const savedConversationsSchema = z
  .array(
    z.object({
      taskId: z.string(),
      runId: z.string(),
      blocks: z
        .array(
          z.discriminatedUnion("kind", [
            z.object({
              kind: z.literal("user"),
              id: z.string(),
              text: z.string().max(50_000),
            }),
            z.object({
              kind: z.literal("agent"),
              id: z.string(),
              text: z.string().max(50_000),
              complete: z.boolean(),
            }),
          ]),
        )
        .max(100),
    }),
  )
  .max(20);
