import {
  createDashboardInput,
  dashboardIdInput,
  dashboardRecordSchema,
  dashboardSummarySchema,
  ensureHomeCanvasInput,
  listDashboardsInput,
  renameDashboardInput,
  saveFreeformInput,
  setGenerationTaskInput,
  setPinnedInput,
} from "@posthog/core/canvas/dashboardSchemas";
import { DASHBOARDS_SERVICE } from "@posthog/core/canvas/identifiers";
import type { IDashboardsService } from "@posthog/core/canvas/services";
import { publicProcedure, router } from "@posthog/host-trpc/trpc";
import { z } from "zod";

export const dashboardsRouter = router({
  list: publicProcedure
    .input(listDashboardsInput)
    .output(z.array(dashboardSummarySchema))
    .query(({ ctx, input }) =>
      ctx.container
        .get<IDashboardsService>(DASHBOARDS_SERVICE)
        .list(input.channelId),
    ),
  get: publicProcedure
    .input(dashboardIdInput)
    .output(dashboardRecordSchema.nullable())
    .query(({ ctx, input }) =>
      ctx.container.get<IDashboardsService>(DASHBOARDS_SERVICE).get(input.id),
    ),
  create: publicProcedure
    .input(createDashboardInput)
    .output(dashboardRecordSchema)
    .mutation(({ ctx, input }) =>
      ctx.container.get<IDashboardsService>(DASHBOARDS_SERVICE).create(input),
    ),
  saveFreeform: publicProcedure
    .input(saveFreeformInput)
    .output(dashboardRecordSchema)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<IDashboardsService>(DASHBOARDS_SERVICE)
        .saveFreeform(input),
    ),
  setGenerationTask: publicProcedure
    .input(setGenerationTaskInput)
    .output(dashboardRecordSchema)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<IDashboardsService>(DASHBOARDS_SERVICE)
        .setGenerationTask(input),
    ),
  setPinned: publicProcedure
    .input(setPinnedInput)
    .output(dashboardRecordSchema)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<IDashboardsService>(DASHBOARDS_SERVICE)
        .setPinned(input),
    ),
  rename: publicProcedure
    .input(renameDashboardInput)
    .output(dashboardRecordSchema)
    .mutation(({ ctx, input }) =>
      ctx.container.get<IDashboardsService>(DASHBOARDS_SERVICE).rename(input),
    ),
  ensureHomeCanvas: publicProcedure
    .input(ensureHomeCanvasInput)
    .output(dashboardRecordSchema)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<IDashboardsService>(DASHBOARDS_SERVICE)
        .ensureHomeCanvas(input.channelId),
    ),
  resetHomeCanvas: publicProcedure
    .input(ensureHomeCanvasInput)
    .output(dashboardRecordSchema)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<IDashboardsService>(DASHBOARDS_SERVICE)
        .resetHomeCanvas(input.channelId),
    ),
  delete: publicProcedure
    .input(dashboardIdInput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<IDashboardsService>(DASHBOARDS_SERVICE)
        .delete(input.id),
    ),
});
