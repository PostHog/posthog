import { publicProcedure, router } from "@posthog/host-trpc/trpc";
import { PI_SESSION_SERVICE } from "@posthog/workspace-server/services/pi-session/identifiers";
import type { PiSessionService } from "@posthog/workspace-server/services/pi-session/pi-session";
import {
  piConversationOutput,
  piSessionAvailableModelsOutput,
  piSessionBashInput,
  piSessionBashOutput,
  piSessionCancelledOutput,
  piSessionCommandsOutput,
  piSessionCompactInput,
  piSessionCycleModelOutput,
  piSessionEnabledInput,
  piSessionEntriesInput,
  piSessionEntryInput,
  piSessionExportInput,
  piSessionExportOutput,
  piSessionForkMessagesOutput,
  piSessionForkOutput,
  piSessionHealthOutput,
  piSessionLastAssistantTextOutput,
  piSessionMessageInput,
  piSessionModelInput,
  piSessionModelOutput,
  piSessionNameInput,
  piSessionNewInput,
  piSessionPathInput,
  piSessionPromptAndWaitInput,
  piSessionPromptInput,
  piSessionQueueModeInput,
  piSessionStartOutput,
  piSessionStatusOutput,
  piSessionStderrOutput,
  piSessionThinkingCycleOutput,
  piSessionThinkingLevelInput,
  piSessionTimeoutInput,
  piSessionTranscriptInput,
  piSessionUnknownOutput,
  resumePiSessionInput,
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

  prompt: publicProcedure
    .input(piSessionPromptInput)
    .mutation(({ ctx, input }) =>
      getService(ctx.container).prompt(
        input.taskId,
        input.prompt,
        input.images,
      ),
    ),

  steer: publicProcedure
    .input(piSessionMessageInput)
    .mutation(({ ctx, input }) =>
      getService(ctx.container).steer(
        input.taskId,
        input.message,
        input.images,
      ),
    ),

  followUp: publicProcedure
    .input(piSessionMessageInput)
    .mutation(({ ctx, input }) =>
      getService(ctx.container).followUp(
        input.taskId,
        input.message,
        input.images,
      ),
    ),

  abort: publicProcedure
    .input(piSessionTranscriptInput)
    .mutation(({ ctx, input }) =>
      getService(ctx.container).abort(input.taskId),
    ),

  newSession: publicProcedure
    .input(piSessionNewInput)
    .output(piSessionCancelledOutput)
    .mutation(({ ctx, input }) =>
      getService(ctx.container).newSession(input.taskId, input.parentSession),
    ),

  setModel: publicProcedure
    .input(piSessionModelInput)
    .output(piSessionModelOutput)
    .mutation(({ ctx, input }) =>
      getService(ctx.container).setModel(
        input.taskId,
        input.provider,
        input.modelId,
      ),
    ),

  cycleModel: publicProcedure
    .input(piSessionTranscriptInput)
    .output(piSessionCycleModelOutput)
    .mutation(({ ctx, input }) =>
      getService(ctx.container).cycleModel(input.taskId),
    ),

  availableModels: publicProcedure
    .input(piSessionTranscriptInput)
    .output(piSessionAvailableModelsOutput)
    .query(({ ctx, input }) =>
      getService(ctx.container).availableModels(input.taskId),
    ),

  setThinkingLevel: publicProcedure
    .input(piSessionThinkingLevelInput)
    .mutation(({ ctx, input }) =>
      getService(ctx.container).setThinkingLevel(input.taskId, input.level),
    ),

  cycleThinkingLevel: publicProcedure
    .input(piSessionTranscriptInput)
    .output(piSessionThinkingCycleOutput)
    .mutation(({ ctx, input }) =>
      getService(ctx.container).cycleThinkingLevel(input.taskId),
    ),

  setSteeringMode: publicProcedure
    .input(piSessionQueueModeInput)
    .mutation(({ ctx, input }) =>
      getService(ctx.container).setSteeringMode(input.taskId, input.mode),
    ),

  setFollowUpMode: publicProcedure
    .input(piSessionQueueModeInput)
    .mutation(({ ctx, input }) =>
      getService(ctx.container).setFollowUpMode(input.taskId, input.mode),
    ),

  compact: publicProcedure
    .input(piSessionCompactInput)
    .output(piSessionUnknownOutput)
    .mutation(({ ctx, input }) =>
      getService(ctx.container).compact(input.taskId, input.customInstructions),
    ),

  setAutoCompaction: publicProcedure
    .input(piSessionEnabledInput)
    .mutation(({ ctx, input }) =>
      getService(ctx.container).setAutoCompaction(input.taskId, input.enabled),
    ),

  setAutoRetry: publicProcedure
    .input(piSessionEnabledInput)
    .mutation(({ ctx, input }) =>
      getService(ctx.container).setAutoRetry(input.taskId, input.enabled),
    ),

  abortRetry: publicProcedure
    .input(piSessionTranscriptInput)
    .mutation(({ ctx, input }) =>
      getService(ctx.container).abortRetry(input.taskId),
    ),

  bash: publicProcedure
    .input(piSessionBashInput)
    .output(piSessionBashOutput)
    .mutation(({ ctx, input }) =>
      getService(ctx.container).bash(input.taskId, input.command),
    ),

  abortBash: publicProcedure
    .input(piSessionTranscriptInput)
    .mutation(({ ctx, input }) =>
      getService(ctx.container).abortBash(input.taskId),
    ),

  sessionStats: publicProcedure
    .input(piSessionTranscriptInput)
    .output(piSessionUnknownOutput)
    .query(({ ctx, input }) =>
      getService(ctx.container).sessionStats(input.taskId),
    ),

  exportHtml: publicProcedure
    .input(piSessionExportInput)
    .output(piSessionExportOutput)
    .mutation(({ ctx, input }) =>
      getService(ctx.container).exportHtml(input.taskId, input.outputPath),
    ),

  switchSession: publicProcedure
    .input(piSessionPathInput)
    .output(piSessionCancelledOutput)
    .mutation(({ ctx, input }) =>
      getService(ctx.container).switchSession(input.taskId, input.sessionPath),
    ),

  fork: publicProcedure
    .input(piSessionEntryInput)
    .output(piSessionForkOutput)
    .mutation(({ ctx, input }) =>
      getService(ctx.container).fork(input.taskId, input.entryId),
    ),

  clone: publicProcedure
    .input(piSessionTranscriptInput)
    .output(piSessionCancelledOutput)
    .mutation(({ ctx, input }) =>
      getService(ctx.container).clone(input.taskId),
    ),

  forkMessages: publicProcedure
    .input(piSessionTranscriptInput)
    .output(piSessionForkMessagesOutput)
    .query(({ ctx, input }) =>
      getService(ctx.container).forkMessages(input.taskId),
    ),

  setSessionName: publicProcedure
    .input(piSessionNameInput)
    .mutation(({ ctx, input }) =>
      getService(ctx.container).setSessionName(input.taskId, input.name),
    ),

  status: publicProcedure
    .input(piSessionTranscriptInput)
    .output(piSessionStatusOutput)
    .query(({ ctx, input }) => getService(ctx.container).status(input.taskId)),

  conversation: publicProcedure
    .input(piSessionTranscriptInput)
    .output(piConversationOutput)
    .query(({ ctx, input }) =>
      getService(ctx.container).conversation(input.taskId),
    ),

  entries: publicProcedure
    .input(piSessionEntriesInput)
    .query(({ ctx, input }) =>
      getService(ctx.container).entries(input.taskId, input.since),
    ),

  tree: publicProcedure
    .input(piSessionTranscriptInput)
    .output(piSessionUnknownOutput)
    .query(({ ctx, input }) => getService(ctx.container).tree(input.taskId)),

  lastAssistantText: publicProcedure
    .input(piSessionTranscriptInput)
    .output(piSessionLastAssistantTextOutput)
    .query(({ ctx, input }) =>
      getService(ctx.container).lastAssistantText(input.taskId),
    ),

  messages: publicProcedure
    .input(piSessionTranscriptInput)
    .output(piSessionUnknownOutput)
    .query(({ ctx, input }) =>
      getService(ctx.container).messages(input.taskId),
    ),

  commands: publicProcedure
    .input(piSessionTranscriptInput)
    .output(piSessionCommandsOutput)
    .query(({ ctx, input }) =>
      getService(ctx.container).commands(input.taskId),
    ),

  waitForIdle: publicProcedure
    .input(piSessionTimeoutInput)
    .mutation(({ ctx, input }) =>
      getService(ctx.container).waitForIdle(input.taskId, input.timeout),
    ),

  collectEvents: publicProcedure
    .input(piSessionTimeoutInput)
    .output(piSessionUnknownOutput)
    .mutation(({ ctx, input }) =>
      getService(ctx.container).collectEvents(input.taskId, input.timeout),
    ),

  promptAndWait: publicProcedure
    .input(piSessionPromptAndWaitInput)
    .output(piSessionUnknownOutput)
    .mutation(({ ctx, input }) =>
      getService(ctx.container).promptAndWait(
        input.taskId,
        input.prompt,
        input.images,
        input.timeout,
      ),
    ),

  stderr: publicProcedure
    .input(piSessionTranscriptInput)
    .output(piSessionStderrOutput)
    .query(({ ctx, input }) => getService(ctx.container).stderr(input.taskId)),

  stop: publicProcedure
    .input(piSessionTranscriptInput)
    .mutation(({ ctx, input }) => getService(ctx.container).stop(input.taskId)),

  health: publicProcedure
    .input(piSessionTranscriptInput)
    .output(piSessionHealthOutput)
    .query(({ ctx, input }) => getService(ctx.container).health(input.taskId)),

  onEvent: publicProcedure
    .input(piSessionTranscriptInput)
    .subscription(async function* (opts) {
      const service = getService(opts.ctx.container);
      const iterable = service.toIterable("event", { signal: opts.signal });
      for await (const payload of iterable) {
        if (payload.taskId === opts.input.taskId) {
          yield payload.event;
        }
      }
    }),
});
