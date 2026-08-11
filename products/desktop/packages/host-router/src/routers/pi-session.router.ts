import { publicProcedure, router } from "@posthog/host-trpc/trpc";
import { PI_SESSION_SERVICE } from "@posthog/workspace-server/services/pi-session/identifiers";
import type { PiSessionService } from "@posthog/workspace-server/services/pi-session/pi-session";
import {
  piExtensionUIResponseInput,
  piProjectTrustOutput,
  piQueueSnapshotOutput,
  piRpcResponseSchema,
  piSessionConfigInput,
  piSessionConfigOutput,
  piSessionHealthOutput,
  piSessionRpcInput,
  piSessionStartOutput,
  piSessionTaskInput,
  respondMcpToolPermissionInput,
  resumePiSessionInput,
  setPiProjectTrustInput,
  startPiSessionInput,
} from "@posthog/workspace-server/services/pi-session/schemas";

const getService = (container: { get<T>(token: symbol): T }) =>
  container.get<PiSessionService>(PI_SESSION_SERVICE);

export const piSessionRouter = router({
  start: publicProcedure
    .input(startPiSessionInput)
    .output(piSessionStartOutput)
    .mutation(({ ctx, input }) => getService(ctx.container).start(input)),

  resume: publicProcedure
    .input(resumePiSessionInput)
    .mutation(({ ctx, input }) => getService(ctx.container).resume(input)),

  rpc: publicProcedure
    .input(piSessionRpcInput)
    .output(piRpcResponseSchema)
    .mutation(({ ctx, input }) =>
      getService(ctx.container).request(input.taskId, input.command),
    ),

  stop: publicProcedure
    .input(piSessionTaskInput)
    .mutation(({ ctx, input }) => getService(ctx.container).stop(input.taskId)),

  health: publicProcedure
    .input(piSessionTaskInput)
    .output(piSessionHealthOutput)
    .query(({ ctx, input }) => getService(ctx.container).health(input.taskId)),

  readSessionConfig: publicProcedure
    .input(piSessionConfigInput)
    .output(piSessionConfigOutput)
    .query(({ ctx, input }) =>
      getService(ctx.container).readSessionConfig(input.downloadUrl),
    ),

  getQueue: publicProcedure
    .input(piSessionTaskInput)
    .output(piQueueSnapshotOutput)
    .query(({ ctx, input }) =>
      getService(ctx.container).getQueue(input.taskId),
    ),

  clearQueue: publicProcedure
    .input(piSessionTaskInput)
    .output(piQueueSnapshotOutput)
    .mutation(({ ctx, input }) =>
      getService(ctx.container).clearQueue(input.taskId),
    ),

  respondMcpToolPermission: publicProcedure
    .input(respondMcpToolPermissionInput)
    .mutation(({ ctx, input }) =>
      getService(ctx.container).respondMcpToolPermission(
        input.taskId,
        input.request,
        input.decision,
      ),
    ),

  onMcpToolPermissionRequest: publicProcedure
    .input(piSessionTaskInput)
    .subscription(async function* (opts) {
      const service = getService(opts.ctx.container);
      const iterable = service.toIterable("mcpPermissionRequest", {
        signal: opts.signal,
      });
      for (const request of service.getPendingMcpToolPermissions(
        opts.input.taskId,
      )) {
        yield request;
      }
      for await (const payload of iterable) {
        if (payload.taskId === opts.input.taskId) {
          yield payload.request;
        }
      }
    }),

  getProjectTrust: publicProcedure
    .input(piSessionTaskInput)
    .output(piProjectTrustOutput)
    .query(({ ctx, input }) =>
      getService(ctx.container).getProjectTrust(input.taskId),
    ),

  setProjectTrusted: publicProcedure
    .input(setPiProjectTrustInput)
    .mutation(({ ctx, input }) =>
      getService(ctx.container).setProjectTrusted(input.taskId, input.trusted),
    ),

  respondToExtensionUI: publicProcedure
    .input(piExtensionUIResponseInput)
    .mutation(({ ctx, input }) =>
      getService(ctx.container).respondToExtensionUI(
        input.taskId,
        input.response,
      ),
    ),

  onEvent: publicProcedure
    .input(piSessionTaskInput)
    .subscription(async function* (opts) {
      const service = getService(opts.ctx.container);
      const iterable = service.toIterable("event", { signal: opts.signal });
      for await (const payload of iterable) {
        if (payload.taskId === opts.input.taskId) {
          yield payload.event;
        }
      }
    }),

  onExtensionEvent: publicProcedure
    .input(piSessionTaskInput)
    .subscription(({ ctx, input, signal }) =>
      getService(ctx.container).extensionEvents(input.taskId, signal),
    ),
});
