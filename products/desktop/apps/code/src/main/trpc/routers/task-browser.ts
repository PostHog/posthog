import { z } from "zod";
import { container } from "../../di/container";
import { TASK_BROWSER_SERVICE } from "../../di/tokens";
import {
  browserSettingsSchema,
  permissionResponseInput,
  registerTabInput,
  setSitePolicyInput,
  TaskBrowserEvent,
} from "../../platform-adapters/task-browser/schemas";
import type { TaskBrowserService } from "../../platform-adapters/task-browser/service";
import { publicProcedure, router } from "../trpc";

const getService = () =>
  container.get<TaskBrowserService>(TASK_BROWSER_SERVICE);

export const taskBrowserRouter = router({
  register: publicProcedure
    .input(registerTabInput)
    .mutation(({ input }) => getService().register(input)),

  unregister: publicProcedure
    .input(z.object({ browserId: z.string(), webContentsId: z.number().int() }))
    .mutation(({ input }) =>
      getService().unregister(input.browserId, input.webContentsId),
    ),

  onOpenRequest: publicProcedure.subscription(async function* (opts) {
    for await (const data of getService().toIterable(
      TaskBrowserEvent.OpenRequest,
      { signal: opts.signal },
    )) {
      yield data;
    }
  }),

  onCloseRequest: publicProcedure.subscription(async function* (opts) {
    for await (const data of getService().toIterable(
      TaskBrowserEvent.CloseRequest,
      { signal: opts.signal },
    )) {
      yield data;
    }
  }),

  onPermissionRequest: publicProcedure.subscription(async function* (opts) {
    for await (const data of getService().toIterable(
      TaskBrowserEvent.PermissionRequest,
      { signal: opts.signal },
    )) {
      yield data;
    }
  }),

  onPermissionSettled: publicProcedure.subscription(async function* (opts) {
    for await (const data of getService().toIterable(
      TaskBrowserEvent.PermissionSettled,
      { signal: opts.signal },
    )) {
      yield data;
    }
  }),

  respondToPermission: publicProcedure
    .input(permissionResponseInput)
    .mutation(({ input }) =>
      getService().respondToPermission(input.requestId, input.decision),
    ),

  getSettings: publicProcedure
    .output(browserSettingsSchema)
    .query(() => getService().settings()),

  setSitePolicy: publicProcedure
    .input(setSitePolicyInput)
    .mutation(({ input }) =>
      getService().sites.set(input.origin, input.policy),
    ),

  setFullCdpAccess: publicProcedure
    .input(z.object({ enabled: z.boolean() }))
    .mutation(({ input }) => getService().setFullCdpAccess(input.enabled)),

  clearBrowsingData: publicProcedure.mutation(() =>
    getService().clearBrowsingData(),
  ),
});
