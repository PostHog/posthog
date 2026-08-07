import { useHostTRPC } from "@posthog/host-router/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

export function useAgentPlugins() {
  const trpc = useHostTRPC();
  return useQuery(trpc.agentPlugins.list.queryOptions());
}

function useInvalidateAgentPlugins(): () => void {
  const trpc = useHostTRPC();
  const queryClient = useQueryClient();
  return useCallback(() => {
    void queryClient.invalidateQueries(trpc.agentPlugins.pathFilter());
  }, [queryClient, trpc]);
}

export function useSelectAgentPlugin() {
  const trpc = useHostTRPC();
  return useMutation(trpc.agentPlugins.select.mutationOptions());
}

export function useRegisterAgentPlugin() {
  const trpc = useHostTRPC();
  const invalidate = useInvalidateAgentPlugins();
  return useMutation(
    trpc.agentPlugins.register.mutationOptions({ onSuccess: invalidate }),
  );
}

export function useSetAgentPluginEnabled() {
  const trpc = useHostTRPC();
  const invalidate = useInvalidateAgentPlugins();
  return useMutation(
    trpc.agentPlugins.setEnabled.mutationOptions({ onSuccess: invalidate }),
  );
}

export function useUnregisterAgentPlugin() {
  const trpc = useHostTRPC();
  const invalidate = useInvalidateAgentPlugins();
  return useMutation(
    trpc.agentPlugins.unregister.mutationOptions({ onSuccess: invalidate }),
  );
}
