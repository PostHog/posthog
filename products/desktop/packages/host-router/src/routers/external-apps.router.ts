import { publicProcedure, router } from "@posthog/host-trpc/trpc";
import type { ExternalAppsService } from "@posthog/workspace-server/services/external-apps/external-apps";
import { EXTERNAL_APPS_SERVICE } from "@posthog/workspace-server/services/external-apps/identifiers";
import {
  copyPathInput,
  getDetectedAppsOutput,
  getLastUsedOutput,
  openInAppInput,
  openInAppOutput,
  setLastUsedInput,
} from "@posthog/workspace-server/services/external-apps/schemas";

export const externalAppsRouter = router({
  getDetectedApps: publicProcedure
    .output(getDetectedAppsOutput)
    .query(({ ctx }) =>
      ctx.container
        .get<ExternalAppsService>(EXTERNAL_APPS_SERVICE)
        .getDetectedApps(),
    ),

  openInApp: publicProcedure
    .input(openInAppInput)
    .output(openInAppOutput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<ExternalAppsService>(EXTERNAL_APPS_SERVICE)
        .openInApp(input.appId, input.targetPath),
    ),

  setLastUsed: publicProcedure
    .input(setLastUsedInput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<ExternalAppsService>(EXTERNAL_APPS_SERVICE)
        .setLastUsed(input.appId),
    ),

  getLastUsed: publicProcedure
    .output(getLastUsedOutput)
    .query(({ ctx }) =>
      ctx.container
        .get<ExternalAppsService>(EXTERNAL_APPS_SERVICE)
        .getLastUsed(),
    ),

  copyPath: publicProcedure
    .input(copyPathInput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<ExternalAppsService>(EXTERNAL_APPS_SERVICE)
        .copyPath(input.targetPath),
    ),
});
