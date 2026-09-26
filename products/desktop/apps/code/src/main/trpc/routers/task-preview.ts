import { z } from "zod";
import { authorizePartitionPreview } from "../../platform-adapters/electron-task-preview";
import { publicProcedure, router } from "../trpc";

export const taskPreviewRouter = router({
  authorize: publicProcedure
    .input(z.object({ url: z.string().max(4_000) }))
    .output(z.string().nullable())
    .mutation(({ input }) => authorizePartitionPreview(input.url)),
});
