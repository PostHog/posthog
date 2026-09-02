import {
  canvasBuildActionInputSchema,
  canvasBuildLifecycleSchema,
  canvasBuildRecordSchema,
} from "@posthog/core/canvas/canvasBuildSchemas";
import {
  canvasActionDefinitionSchema,
  canvasActionInvokeInput,
  canvasActionResultSchema,
  canvasBuildsInput,
  canvasDraftSchema,
  canvasSourceInput,
  canvasSourceSchema,
  canvasStateEntrySchema,
  canvasStateListInput,
  canvasStateSetInput,
  canvasVersionSchema,
  createDashboardInput,
  dashboardIdInput,
  dashboardRecordSchema,
  fileDashboardInput,
  listComponentsInput,
  listDashboardsInput,
  promoteCanvasInput,
  renameDashboardInput,
  reportCanvasErrorInput,
  requestCanvasAgentInput,
  revertCanvasInput,
  saveContextInput,
  setGenerationTaskInput,
  setPinnedInput,
} from "@posthog/core/canvas/dashboardSchemas";
import {
  canvasLayoutInput,
  canvasLayoutResultSchema,
  patchLayoutInput,
  publishLayoutInput,
} from "@posthog/core/canvas/gridLayoutSchemas";
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
  listComponents: publicProcedure
    .input(listComponentsInput)
    .output(z.array(dashboardRecordSchema))
    .query(({ ctx, input }) =>
      ctx.container
        .get<IDashboardsService>(DASHBOARDS_SERVICE)
        .listComponents(input),
    ),
  listAll: publicProcedure
    .output(z.array(dashboardRecordSchema))
    .query(({ ctx }) =>
      ctx.container.get<IDashboardsService>(DASHBOARDS_SERVICE).listAll(),
    ),
  get: publicProcedure
    .input(dashboardIdInput)
    .output(dashboardRecordSchema.nullable())
    .query(({ ctx, input }) =>
      ctx.container.get<IDashboardsService>(DASHBOARDS_SERVICE).get(input.id),
    ),
  // A query despite the POST underneath: home is an idempotent get-or-create,
  // and query semantics give the surface caching and dedupe for free.
  home: publicProcedure
    .output(dashboardRecordSchema)
    .query(({ ctx }) =>
      ctx.container.get<IDashboardsService>(DASHBOARDS_SERVICE).home(),
    ),
  layout: publicProcedure
    .input(canvasLayoutInput)
    .output(canvasLayoutResultSchema)
    .query(({ ctx, input }) =>
      ctx.container
        .get<IDashboardsService>(DASHBOARDS_SERVICE)
        .getLayout(input),
    ),
  publishLayout: publicProcedure
    .input(publishLayoutInput)
    .output(canvasLayoutResultSchema)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<IDashboardsService>(DASHBOARDS_SERVICE)
        .publishLayout(input),
    ),
  patchLayout: publicProcedure
    .input(patchLayoutInput)
    .output(canvasLayoutResultSchema)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<IDashboardsService>(DASHBOARDS_SERVICE)
        .patchLayout(input),
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
  drafts: publicProcedure
    .input(dashboardIdInput)
    .output(z.array(canvasDraftSchema))
    .query(({ ctx, input }) =>
      ctx.container
        .get<IDashboardsService>(DASHBOARDS_SERVICE)
        .listDrafts(input.id),
    ),
  promoteDraft: publicProcedure
    .input(promoteCanvasInput)
    .output(canvasBuildRecordSchema)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<IDashboardsService>(DASHBOARDS_SERVICE)
        .promoteDraft(input),
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
    .input(canvasBuildsInput)
    .output(canvasBuildLifecycleSchema)
    .query(({ ctx, input }) =>
      ctx.container
        .get<IDashboardsService>(DASHBOARDS_SERVICE)
        .getBuilds(input),
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
  file: publicProcedure
    .input(fileDashboardInput)
    .output(dashboardRecordSchema)
    .mutation(({ ctx, input }) =>
      ctx.container.get<IDashboardsService>(DASHBOARDS_SERVICE).file(input),
    ),
  reportError: publicProcedure
    .input(reportCanvasErrorInput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<IDashboardsService>(DASHBOARDS_SERVICE)
        .reportError(input),
    ),
  listState: publicProcedure
    .input(canvasStateListInput)
    .output(z.array(canvasStateEntrySchema))
    .query(({ ctx, input }) =>
      ctx.container
        .get<IDashboardsService>(DASHBOARDS_SERVICE)
        .listState(input),
    ),
  setState: publicProcedure
    .input(canvasStateSetInput)
    .mutation(({ ctx, input }) =>
      ctx.container.get<IDashboardsService>(DASHBOARDS_SERVICE).setState(input),
    ),
  listActions: publicProcedure
    .output(z.array(canvasActionDefinitionSchema))
    .query(({ ctx }) =>
      ctx.container.get<IDashboardsService>(DASHBOARDS_SERVICE).listActions(),
    ),
  invokeAction: publicProcedure
    .input(canvasActionInvokeInput)
    .output(canvasActionResultSchema)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<IDashboardsService>(DASHBOARDS_SERVICE)
        .invokeAction(input),
    ),
  rename: publicProcedure
    .input(renameDashboardInput)
    .output(dashboardRecordSchema)
    .mutation(({ ctx, input }) =>
      ctx.container.get<IDashboardsService>(DASHBOARDS_SERVICE).rename(input),
    ),
  delete: publicProcedure
    .input(dashboardIdInput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<IDashboardsService>(DASHBOARDS_SERVICE)
        .delete(input.id),
    ),
  requestAgent: publicProcedure
    .input(requestCanvasAgentInput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<IDashboardsService>(DASHBOARDS_SERVICE)
        .requestAgent(input),
    ),
});
