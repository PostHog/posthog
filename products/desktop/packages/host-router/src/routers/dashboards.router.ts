import {
  canvasBuildActionInputSchema,
  canvasBuildLifecycleSchema,
  canvasBuildRecordSchema,
} from "@posthog/core/canvas/canvasBuildSchemas";
import {
  canvasSourceInput,
  canvasSourceSchema,
  canvasVersionSchema,
  createDashboardInput,
  dashboardIdInput,
  dashboardRecordSchema,
  ensureHomeCanvasInput,
  listDashboardsInput,
  renameDashboardInput,
  revertCanvasInput,
  saveContextInput,
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
    .output(z.array(dashboardRecordSchema))
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
  source: publicProcedure
    .input(canvasSourceInput)
    .output(canvasSourceSchema)
    .query(({ ctx, input }) =>
      ctx.container
        .get<IDashboardsService>(DASHBOARDS_SERVICE)
        .getSource(input),
    ),
  versions: publicProcedure
    .input(dashboardIdInput)
    .output(z.array(canvasVersionSchema))
    .query(({ ctx, input }) =>
      ctx.container
        .get<IDashboardsService>(DASHBOARDS_SERVICE)
        .listVersions(input.id),
    ),
  revertToVersion: publicProcedure
    .input(revertCanvasInput)
    .output(canvasBuildRecordSchema)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<IDashboardsService>(DASHBOARDS_SERVICE)
        .revertToVersion(input),
    ),
  builds: publicProcedure
    .input(dashboardIdInput)
    .output(canvasBuildLifecycleSchema)
    .query(({ ctx, input }) =>
      ctx.container
        .get<IDashboardsService>(DASHBOARDS_SERVICE)
        .getBuilds(input.id),
    ),
  actOnBuild: publicProcedure
    .input(canvasBuildActionInputSchema)
    .output(canvasBuildRecordSchema)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<IDashboardsService>(DASHBOARDS_SERVICE)
        .actOnBuild(input),
    ),
  create: publicProcedure
    .input(createDashboardInput)
    .output(dashboardRecordSchema)
    .mutation(({ ctx, input }) =>
      ctx.container.get<IDashboardsService>(DASHBOARDS_SERVICE).create(input),
    ),
  saveContext: publicProcedure
    .input(saveContextInput)
    .output(dashboardRecordSchema)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<IDashboardsService>(DASHBOARDS_SERVICE)
        .saveContext(input),
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
