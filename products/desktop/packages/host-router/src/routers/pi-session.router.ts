import { publicProcedure, router } from "@posthog/host-trpc/trpc";
import { PI_SESSION_SERVICE } from "@posthog/workspace-server/services/pi-session/identifiers";
import type { PiSessionService } from "@posthog/workspace-server/services/pi-session/pi-session";
import {
  piExtensionEditorTextAckInput,
  piExtensionEventSchema,
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

  acknowledgeExtensionEditorText: publicProcedure
    .input(piExtensionEditorTextAckInput)
    .mutation(({ ctx, input }) =>
      getService(ctx.container).acknowledgeExtensionEditorText(
        input.taskId,
        input.id,
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
    .subscription(async function* (opts) {
      const service = getService(opts.ctx.container);
      const iterator = service
        .toIterable("extensionEvent", { signal: opts.signal })
        [Symbol.asyncIterator]();
      let next = iterator.next();
      const snapshot = service.getExtensionStateSnapshot(opts.input.taskId);

      try {
        yield piExtensionEventSchema.parse(snapshot);

        while (true) {
          const result = await next;
          if (result.done) {
            return;
          }
          if (result.value.taskId === opts.input.taskId) {
            const event = piExtensionEventSchema.parse(result.value.event);
            if (event.type === "extension_session_reset") {
              yield event;
              return;
            }
            next = iterator.next();
            yield event;
          } else {
            next = iterator.next();
          }
        }
      } finally {
        await iterator.return?.();
      }
    }),
});
