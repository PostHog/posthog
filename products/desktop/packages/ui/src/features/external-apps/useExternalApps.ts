import { useHostTRPCClient } from "@posthog/host-router/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo } from "react";

const DETECTED_APPS_KEY = ["external-apps", "detected"] as const;
const LAST_USED_KEY = ["external-apps", "last-used"] as const;

export function useExternalApps() {
  const client = useHostTRPCClient();
  const queryClient = useQueryClient();

  const { data: detectedApps = [], isLoading: appsLoading } = useQuery({
    queryKey: DETECTED_APPS_KEY,
    queryFn: () => client.externalApps.getDetectedApps.query(),
    staleTime: 60_000,
  });

  const { data: lastUsedAppId, isLoading: lastUsedLoading } = useQuery({
    queryKey: LAST_USED_KEY,
    queryFn: async () =>
      (await client.externalApps.getLastUsed.query()).lastUsedApp ?? null,
    staleTime: 60_000,
  });

  const setLastUsedMutation = useMutation({
    mutationFn: (appId: string) =>
      client.externalApps.setLastUsed.mutate({ appId }),
    onSuccess: (_, appId) => {
      queryClient.setQueryData(LAST_USED_KEY, appId);
    },
  });

  const isLoading = appsLoading || lastUsedLoading;

  const defaultApp = useMemo(() => {
    if (lastUsedAppId) {
      const app = detectedApps.find((a) => a.id === lastUsedAppId);
      if (app) return app;
    }
    return detectedApps[0] || null;
  }, [detectedApps, lastUsedAppId]);

  const setLastUsedApp = useCallback(
    async (appId: string) => {
      await setLastUsedMutation.mutateAsync(appId);
    },
    [setLastUsedMutation],
  );

  return {
    detectedApps,
    lastUsedAppId,
    defaultApp,
    isLoading,
    setLastUsedApp,
  };
}
