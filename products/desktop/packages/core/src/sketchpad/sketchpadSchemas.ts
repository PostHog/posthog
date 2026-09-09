import { sketchpadPresenceInputSchema } from "@posthog/shared";
import { z } from "zod";

export const sketchpadIdInput = z.object({ id: z.string().min(1) });

export const sketchpadSendPresenceInput = z.object({
  id: z.string().min(1),
  presence: sketchpadPresenceInputSchema,
});

export const sketchpadListInput = z.object({
  channelId: z.string().min(1).optional(),
});

export const createSketchpadInput = z.object({
  channelId: z.string().min(1),
  name: z.string().min(1).max(120),
});

export const updateSketchpadInput = z.object({
  id: z.string().min(1),
  patch: z.object({
    name: z.string().min(1).max(120).optional(),
    channelId: z.string().min(1).optional(),
    pinned: z.boolean().optional(),
  }),
});
export type SketchpadMetadataPatch = z.infer<
  typeof updateSketchpadInput
>["patch"];

export const sketchpadOpsSinceInput = z.object({
  id: z.string().min(1),
  since: z.number().int().min(0),
  limit: z.number().int().min(1).max(1000).optional(),
});
