import { publicProcedure, router } from "@posthog/host-trpc/trpc";
import type { AgentPluginsService } from "@posthog/workspace-server/services/agent-plugins/agent-plugins";
import { AGENT_PLUGINS_SERVICE } from "@posthog/workspace-server/services/agent-plugins/identifiers";
import {
  agentPluginIdInput,
  agentPluginInstallation,
  listAgentPluginsOutput,
  previewAgentPluginInput,
  registerAgentPluginInput,
  selectAgentPluginOutput,
  setAgentPluginEnabledInput,
} from "@posthog/workspace-server/services/agent-plugins/schemas";

export const agentPluginsRouter = router({
  list: publicProcedure
    .output(listAgentPluginsOutput)
    .query(({ ctx }) =>
      ctx.container.get<AgentPluginsService>(AGENT_PLUGINS_SERVICE).list(),
    ),
  preview: publicProcedure
    .input(previewAgentPluginInput)
    .output(selectAgentPluginOutput.unwrap())
    .query(({ ctx, input }) =>
      ctx.container
        .get<AgentPluginsService>(AGENT_PLUGINS_SERVICE)
        .preview(input.sourcePath),
    ),
  select: publicProcedure
    .output(selectAgentPluginOutput)
    .mutation(({ ctx }) =>
      ctx.container
        .get<AgentPluginsService>(AGENT_PLUGINS_SERVICE)
        .selectDirectory(),
    ),
  register: publicProcedure
    .input(registerAgentPluginInput)
    .output(agentPluginInstallation)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<AgentPluginsService>(AGENT_PLUGINS_SERVICE)
        .register(input.sourcePath),
    ),
  setEnabled: publicProcedure
    .input(setAgentPluginEnabledInput)
    .output(agentPluginInstallation)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<AgentPluginsService>(AGENT_PLUGINS_SERVICE)
        .setEnabled(input.id, input.enabled),
    ),
  unregister: publicProcedure
    .input(agentPluginIdInput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<AgentPluginsService>(AGENT_PLUGINS_SERVICE)
        .unregister(input.id),
    ),
});
