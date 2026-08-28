import { useHostTRPCClient } from "@posthog/host-router/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect } from "react";

export const USAGE_QUERY_KEY = ["billing", "usage", "latest"] as const;

export function useUsage({ enabled = true }: { enabled?: boolean } = {}) {
  const client = useHostTRPCClient();
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: USAGE_QUERY_KEY,
    queryFn: () => client.usageMonitor.getLatest.query(),
    enabled,
  });
  const { mutateAsync: refreshUsage } = useMutation({
    mutationFn: () => client.usageMonitor.refresh.mutate(),
  });

  useEffect(() => {
    if (!enabled) return;
    const sub = client.usageMonitor.onUsageUpdated.subscribe(undefined, {
      onData: (data) => {
        queryClient.setQueryData(USAGE_QUERY_KEY, data);
      },
    });
    return () => sub.unsubscribe();
  }, [enabled, client, queryClient]);

  const refetch = useCallback(async () => {
    const fresh = await refreshUsage();
    if (fresh) {
      queryClient.setQueryData(USAGE_QUERY_KEY, fresh);
    }
    return fresh;
  }, [refreshUsage, queryClient]);

  return {
    usage: query.data ?? null,
    isLoading: query.isLoading,
    refetch,
  };
}
