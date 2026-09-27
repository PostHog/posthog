import { TASK_BROWSER_SERVICE } from "@posthog/core/task-browser/identifiers";
import {
  browserSettingsSchema,
  forgetTabInput,
  permissionResponseInput,
  registerTabInput,
  setFullCdpAccessInput,
  setSitePolicyInput,
  TaskBrowserEvent,
  unregisterTabInput,
} from "@posthog/core/task-browser/schemas";
import type { TaskBrowserService } from "@posthog/core/task-browser/taskBrowserService";
import type { ServiceResolver } from "@posthog/host-trpc/context";
import { publicProcedure, router } from "@posthog/host-trpc/trpc";

const svc = (container: ServiceResolver) =>
  container.get<TaskBrowserService>(TASK_BROWSER_SERVICE);

function events<
  K extends (typeof TaskBrowserEvent)[keyof typeof TaskBrowserEvent],
>(event: K) {
  return publicProcedure.subscription(async function* (opts) {
    for await (const data of svc(opts.ctx.container).toIterable(event, {
      signal: opts.signal,
    })) {
      yield data;
    }
  });
}

export const taskBrowserRouter = router({
  register: publicProcedure
    .input(registerTabInput)
    .mutation(({ ctx, input }) => svc(ctx.container).register(input)),

  unregister: publicProcedure
    .input(unregisterTabInput)
    .mutation(({ ctx, input }) =>
      svc(ctx.container).unregister(
        input.browserId,
        input.webContentsId,
        input.url,
      ),
    ),

  onOpenRequest: events(TaskBrowserEvent.OpenRequest),
  onCloseRequest: events(TaskBrowserEvent.CloseRequest),
  onPermissionRequest: events(TaskBrowserEvent.PermissionRequest),
  onPermissionSettled: events(TaskBrowserEvent.PermissionSettled),

  respondToPermission: publicProcedure
    .input(permissionResponseInput)
    .mutation(({ ctx, input }) =>
      svc(ctx.container).respondToPermission(input.requestId, input.decision),
    ),

  getSettings: publicProcedure
    .output(browserSettingsSchema)
    .query(({ ctx }) => svc(ctx.container).settings()),

  setSitePolicy: publicProcedure
    .input(setSitePolicyInput)
    .mutation(({ ctx, input }) =>
      svc(ctx.container).setSitePolicy(input.origin, input.policy),
    ),

  setFullCdpAccess: publicProcedure
    .input(setFullCdpAccessInput)
    .mutation(({ ctx, input }) =>
      svc(ctx.container).setFullCdpAccess(input.enabled),
    ),

  forgetTab: publicProcedure
    .input(forgetTabInput)
    .mutation(({ ctx, input }) =>
      svc(ctx.container).forgetTab(input.browserId),
    ),

  clearBrowsingData: publicProcedure.mutation(({ ctx }) =>
    svc(ctx.container).clearBrowsingData(),
  ),
});
