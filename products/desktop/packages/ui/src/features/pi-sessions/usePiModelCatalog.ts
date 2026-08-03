import { useHostTRPC } from "@posthog/host-router/react";
import { getCloudUrlFromRegion } from "@posthog/shared";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

export function usePiModelCatalog(enabled: boolean) {
  const trpc = useHostTRPC();
  const cloudRegion = useAuthStateValue((state) => state.cloudRegion);
  const apiHost = useMemo(
    () => (cloudRegion ? getCloudUrlFromRegion(cloudRegion) : null),
    [cloudRegion],
  );

  return useQuery({
    ...trpc.agent.getPiModelCatalog.queryOptions({
      apiHost: apiHost ?? "",
      region: cloudRegion ?? "us",
    }),
    enabled: enabled && apiHost !== null,
  });
}
