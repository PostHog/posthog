import {
  AGENT_PLUGINS_CLIENT,
  type AgentPluginInstallation,
  type AgentPluginPreview,
  type AgentPluginsClient,
} from "@posthog/core/agent-plugins/agentPluginsClient";
import { useService } from "@posthog/di/react";
import {
  type UseMutationResult,
  type UseQueryResult,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

const agentPluginsQueryKey = ["agent-plugins"] as const;

export function useAgentPlugins(): UseQueryResult<
  AgentPluginInstallation[],
  Error
> {
  const client = useService<AgentPluginsClient>(AGENT_PLUGINS_CLIENT);
  return useQuery({
    queryKey: agentPluginsQueryKey,
    queryFn: () => client.list(),
  });
}

function useInvalidateAgentPlugins(): () => void {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({ queryKey: agentPluginsQueryKey });
  };
}

export function useSelectAgentPlugin(): UseMutationResult<
  AgentPluginPreview | null,
  Error,
  void
> {
  const client = useService<AgentPluginsClient>(AGENT_PLUGINS_CLIENT);
  return useMutation({ mutationFn: () => client.select() });
}

export function useRegisterAgentPlugin(): UseMutationResult<
  AgentPluginInstallation,
  Error,
  { selectionToken: string }
> {
  const client = useService<AgentPluginsClient>(AGENT_PLUGINS_CLIENT);
  const invalidate = useInvalidateAgentPlugins();
  return useMutation({
    mutationFn: ({ selectionToken }) => client.register(selectionToken),
    onSuccess: invalidate,
  });
}

export function useSetAgentPluginEnabled(): UseMutationResult<
  AgentPluginInstallation,
  Error,
  { id: string; enabled: boolean }
> {
  const client = useService<AgentPluginsClient>(AGENT_PLUGINS_CLIENT);
  const invalidate = useInvalidateAgentPlugins();
  return useMutation({
    mutationFn: ({ id, enabled }) => client.setEnabled(id, enabled),
    onSuccess: invalidate,
  });
}

export function useUnregisterAgentPlugin(): UseMutationResult<
  void,
  Error,
  { id: string }
> {
  const client = useService<AgentPluginsClient>(AGENT_PLUGINS_CLIENT);
  const invalidate = useInvalidateAgentPlugins();
  return useMutation({
    mutationFn: ({ id }) => client.unregister(id),
    onSuccess: invalidate,
  });
}
