import {
  canvasV2AppendOpsInputSchema,
  canvasV2AppendOpsResultSchema,
  canvasV2BoardIdInput,
  canvasV2ChannelInput,
  canvasV2OpsPageSchema,
  canvasV2OpsSinceInput,
  createCanvasV2BoardInput,
  fileCanvasV2BoardInput,
  renameCanvasV2BoardInput,
} from "@posthog/core/canvas-v2/canvasV2Schemas";
import {
  CANVAS_V2_BOARDS_SERVICE,
  type ICanvasV2BoardsService,
} from "@posthog/core/canvas-v2/identifiers";
import { publicProcedure, router } from "@posthog/host-trpc/trpc";
import {
  canvasV2BoardSchema,
  canvasV2BoardSummarySchema,
} from "@posthog/shared";
import { z } from "zod";

export const canvasV2Router = router({
  list: publicProcedure
    .input(canvasV2ChannelInput)
    .output(z.array(canvasV2BoardSummarySchema))
    .query(({ ctx, input }) =>
      ctx.container
        .get<ICanvasV2BoardsService>(CANVAS_V2_BOARDS_SERVICE)
        .list(input.channelId),
    ),
  listAll: publicProcedure
    .output(z.array(canvasV2BoardSummarySchema))
    .query(({ ctx }) =>
      ctx.container
        .get<ICanvasV2BoardsService>(CANVAS_V2_BOARDS_SERVICE)
        .listAll(),
    ),
  get: publicProcedure
    .input(canvasV2BoardIdInput)
    .output(canvasV2BoardSchema)
    .query(({ ctx, input }) =>
      ctx.container
        .get<ICanvasV2BoardsService>(CANVAS_V2_BOARDS_SERVICE)
        .get(input.id),
    ),
  create: publicProcedure
    .input(createCanvasV2BoardInput)
    .output(canvasV2BoardSchema)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<ICanvasV2BoardsService>(CANVAS_V2_BOARDS_SERVICE)
        .create(input.channelId, input.name),
    ),
  rename: publicProcedure
    .input(renameCanvasV2BoardInput)
    .output(canvasV2BoardSchema)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<ICanvasV2BoardsService>(CANVAS_V2_BOARDS_SERVICE)
        .rename(input.id, input.name),
    ),
  setChannel: publicProcedure
    .input(fileCanvasV2BoardInput)
    .output(canvasV2BoardSchema)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<ICanvasV2BoardsService>(CANVAS_V2_BOARDS_SERVICE)
        .setChannel(input.id, input.channelId),
    ),
  remove: publicProcedure
    .input(canvasV2BoardIdInput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<ICanvasV2BoardsService>(CANVAS_V2_BOARDS_SERVICE)
        .remove(input.id),
    ),
  opsSince: publicProcedure
    .input(canvasV2OpsSinceInput)
    .output(canvasV2OpsPageSchema)
    .query(({ ctx, input }) =>
      ctx.container
        .get<ICanvasV2BoardsService>(CANVAS_V2_BOARDS_SERVICE)
        .opsSince(input.id, input.since, input.limit),
    ),
  appendOps: publicProcedure
    .input(canvasV2AppendOpsInputSchema)
    .output(canvasV2AppendOpsResultSchema)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<ICanvasV2BoardsService>(CANVAS_V2_BOARDS_SERVICE)
        .appendOps(input.id, {
          ops: input.ops,
          actor: input.actor,
          baseSeq: input.baseSeq,
          snapshot: input.snapshot,
        }),
    ),
});
