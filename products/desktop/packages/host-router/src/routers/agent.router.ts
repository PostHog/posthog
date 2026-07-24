import type { ContentBlock } from "@agentclientprotocol/sdk";
import { SLEEP_SERVICE } from "@posthog/core/sleep/identifiers";
import type { SleepService } from "@posthog/core/sleep/sleep";
import { publicProcedure, router } from "@posthog/host-trpc/trpc";
import type { AgentService } from "@posthog/workspace-server/services/agent/agent";
import { AGENT_SERVICE } from "@posthog/workspace-server/services/agent/identifiers";
import {
  AgentServiceEvent,
  cancelPermissionInput,
  cancelPromptInput,
  cancelSessionInput,
  getGatewayModelsInput,
  getGatewayModelsOutput,
  getPreviewConfigOptionsInput,
  getPreviewConfigOptionsOutput,
  listSessionsInput,
  listSessionsOutput,
  notifySessionContextInput,
  promptInput,
  promptOutput,
  reconnectSessionInput,
  recordActivityInput,
  respondToPermissionInput,
  rtkStatusOutput,
  sessionResponseSchema,
  setConfigOptionInput,
  startSessionInput,
  subscribeSessionInput,
} from "@posthog/workspace-server/services/agent/schemas";
import { PROCESS_TRACKING_SERVICE } from "@posthog/workspace-server/services/process-tracking/identifiers";
import type { ProcessTrackingService } from "@posthog/workspace-server/services/process-tracking/process-tracking";
import { SHELL_SERVICE } from "@posthog/workspace-server/services/shell/identifiers";
import type { ShellService } from "@posthog/workspace-server/services/shell/shell";

export const agentRouter = router({
  start: publicProcedure
    .input(startSessionInput)
    .output(sessionResponseSchema)
    .mutation(({ ctx, input }) =>
      ctx.container.get<AgentService>(AGENT_SERVICE).startSession(input),
    ),

  prompt: publicProcedure
    .input(promptInput)
    .output(promptOutput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<AgentService>(AGENT_SERVICE)
        .prompt(input.sessionId, input.prompt as ContentBlock[], {
          steer: input.steer,
        }),
    ),

  cancel: publicProcedure
    .input(cancelSessionInput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<AgentService>(AGENT_SERVICE)
        .cancelSession(input.sessionId),
    ),

  cancelPrompt: publicProcedure
    .input(cancelPromptInput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<AgentService>(AGENT_SERVICE)
        .cancelPrompt(input.sessionId, input.reason),
    ),

  rtkStatus: publicProcedure
    .output(rtkStatusOutput)
    .query(({ ctx }) =>
      ctx.container.get<AgentService>(AGENT_SERVICE).getRtkStatus(),
    ),

  reconnect: publicProcedure
    .input(reconnectSessionInput)
    .output(sessionResponseSchema.nullable())
    .mutation(({ ctx, input }) =>
      ctx.container.get<AgentService>(AGENT_SERVICE).reconnectSession(input),
    ),

  setConfigOption: publicProcedure
    .input(setConfigOptionInput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<AgentService>(AGENT_SERVICE)
        .setSessionConfigOption(input.sessionId, input.configId, input.value),
    ),

  onSessionEvent: publicProcedure
    .input(subscribeSessionInput)
    .subscription(async function* (opts) {
      const service = opts.ctx.container.get<AgentService>(AGENT_SERVICE);
      const targetTaskRunId = opts.input.taskRunId;
      const iterable = service.toIterable(AgentServiceEvent.SessionEvent, {
        signal: opts.signal,
      });

      for await (const event of iterable) {
        if (event.taskRunId === targetTaskRunId) {
          yield event.payload;
        }
      }
    }),

  onPermissionRequest: publicProcedure
    .input(subscribeSessionInput)
    .subscription(async function* (opts) {
      const service = opts.ctx.container.get<AgentService>(AGENT_SERVICE);
      const targetTaskRunId = opts.input.taskRunId;
      const iterable = service.toIterable(AgentServiceEvent.PermissionRequest, {
        signal: opts.signal,
      });

      for await (const event of iterable) {
        if (event.taskRunId === targetTaskRunId) {
          yield event;
        }
      }
    }),

  respondToPermission: publicProcedure
    .input(respondToPermissionInput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<AgentService>(AGENT_SERVICE)
        .respondToPermission(
          input.taskRunId,
          input.toolCallId,
          input.optionId,
          input.customInput,
          input.answers,
        ),
    ),

  cancelPermission: publicProcedure
    .input(cancelPermissionInput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<AgentService>(AGENT_SERVICE)
        .cancelPermission(input.taskRunId, input.toolCallId),
    ),

  listSessions: publicProcedure
    .input(listSessionsInput)
    .output(listSessionsOutput)
    .query(({ ctx, input }) =>
      ctx.container
        .get<AgentService>(AGENT_SERVICE)
        .listSessions(input.taskId)
        .map((s) => ({ taskRunId: s.taskRunId, repoPath: s.repoPath })),
    ),

  notifySessionContext: publicProcedure
    .input(notifySessionContextInput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<AgentService>(AGENT_SERVICE)
        .notifySessionContext(input.sessionId, input.context),
    ),

  hasActiveSessions: publicProcedure.query(({ ctx }) =>
    ctx.container.get<AgentService>(AGENT_SERVICE).hasActiveSessions(),
  ),

  onSessionsIdle: publicProcedure.subscription(async function* (opts) {
    const service = opts.ctx.container.get<AgentService>(AGENT_SERVICE);
    for await (const _ of service.toIterable(AgentServiceEvent.SessionsIdle, {
      signal: opts.signal,
    })) {
      yield true;
    }
  }),

  resetAll: publicProcedure.mutation(async ({ ctx }) => {
    const agentService = ctx.container.get<AgentService>(AGENT_SERVICE);
    await agentService.cleanupAll();

    const shellService = ctx.container.get<ShellService>(SHELL_SERVICE);
    shellService.destroyAll();

    const processTracking = ctx.container.get<ProcessTrackingService>(
      PROCESS_TRACKING_SERVICE,
    );
    processTracking.killAll();

    const sleepService = ctx.container.get<SleepService>(SLEEP_SERVICE);
    sleepService.cleanup();
  }),

  recordActivity: publicProcedure
    .input(recordActivityInput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<AgentService>(AGENT_SERVICE)
        .recordActivity(input.taskRunId),
    ),

  onSessionIdleKilled: publicProcedure.subscription(async function* (opts) {
    const service = opts.ctx.container.get<AgentService>(AGENT_SERVICE);
    for await (const event of service.toIterable(
      AgentServiceEvent.SessionIdleKilled,
      { signal: opts.signal },
    )) {
      yield event;
    }
  }),

  onAgentFileActivity: publicProcedure.subscription(async function* (opts) {
    const service = opts.ctx.container.get<AgentService>(AGENT_SERVICE);
    for await (const event of service.toIterable(
      AgentServiceEvent.AgentFileActivity,
      { signal: opts.signal },
    )) {
      yield event;
    }
  }),

  getGatewayModels: publicProcedure
    .input(getGatewayModelsInput)
    .output(getGatewayModelsOutput)
    .query(({ ctx, input }) =>
      ctx.container
        .get<AgentService>(AGENT_SERVICE)
        .getGatewayModels(input.apiHost),
    ),

  getPreviewConfigOptions: publicProcedure
    .input(getPreviewConfigOptionsInput)
    .output(getPreviewConfigOptionsOutput)
    .query(({ ctx, input }) =>
      ctx.container
        .get<AgentService>(AGENT_SERVICE)
        .getPreviewConfigOptions(input.apiHost, input.adapter),
    ),
});
