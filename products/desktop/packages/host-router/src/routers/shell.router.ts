import { publicProcedure, router } from "@posthog/host-trpc/trpc";
import { SHELL_SERVICE } from "@posthog/workspace-server/services/shell/identifiers";
import {
  createCommandInput,
  createInput,
  executeInput,
  executeOutput,
  resizeInput,
  ShellEvent,
  type ShellEvents,
  sessionIdInput,
  writeInput,
} from "@posthog/workspace-server/services/shell/schemas";
import type { ShellService } from "@posthog/workspace-server/services/shell/shell";

function subscribeFiltered<K extends keyof ShellEvents>(event: K) {
  return publicProcedure
    .input(sessionIdInput)
    .subscription(async function* (opts) {
      const service = opts.ctx.container.get<ShellService>(SHELL_SERVICE);
      const targetSessionId = opts.input.sessionId;
      const iterable = service.toIterable(event, { signal: opts.signal });

      for await (const data of iterable) {
        if (data.sessionId === targetSessionId) {
          yield data;
        }
      }
    });
}

export const shellRouter = router({
  create: publicProcedure
    .input(createInput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<ShellService>(SHELL_SERVICE)
        .create(input.sessionId, input.cwd, input.taskId),
    ),

  createCommand: publicProcedure
    .input(createCommandInput)
    .mutation(({ ctx, input }) =>
      ctx.container.get<ShellService>(SHELL_SERVICE).createCommandSession({
        sessionId: input.sessionId,
        command: input.command,
        cwd: input.cwd,
        taskId: input.taskId,
      }),
    ),

  write: publicProcedure
    .input(writeInput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<ShellService>(SHELL_SERVICE)
        .write(input.sessionId, input.data),
    ),

  resize: publicProcedure
    .input(resizeInput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<ShellService>(SHELL_SERVICE)
        .resize(input.sessionId, input.cols, input.rows),
    ),

  check: publicProcedure
    .input(sessionIdInput)
    .query(({ ctx, input }) =>
      ctx.container.get<ShellService>(SHELL_SERVICE).check(input.sessionId),
    ),

  destroy: publicProcedure
    .input(sessionIdInput)
    .mutation(({ ctx, input }) =>
      ctx.container.get<ShellService>(SHELL_SERVICE).destroy(input.sessionId),
    ),

  getProcess: publicProcedure
    .input(sessionIdInput)
    .query(({ ctx, input }) =>
      ctx.container
        .get<ShellService>(SHELL_SERVICE)
        .getProcess(input.sessionId),
    ),

  execute: publicProcedure
    .input(executeInput)
    .output(executeOutput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<ShellService>(SHELL_SERVICE)
        .execute(input.cwd, input.command),
    ),

  onData: subscribeFiltered(ShellEvent.Data),
  onExit: subscribeFiltered(ShellEvent.Exit),
});
