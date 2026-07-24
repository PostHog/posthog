import { type LoopSchemas, retrieveLoop } from "@posthog/api-client/loops";
import { AUTH_SCOPED_QUERY_META } from "@posthog/ui/features/auth/useCurrentUser";
import { useQuery } from "@tanstack/react-query";
import { loopsKeys } from "./loopsKeys";
import { useLoopsClient } from "./useLoopsClient";

export function useLoop(loopId: string | undefined) {
  const loopsClient = useLoopsClient();

  return useQuery<LoopSchemas.Loop>({
    queryKey: loopsKeys.detail(loopsClient?.projectId ?? null, loopId ?? ""),
    queryFn: async () => {
      if (!loopsClient || !loopId) throw new Error("Not authenticated");
      return await retrieveLoop(
        loopsClient.client,
        loopsClient.projectId,
        loopId,
      );
    },
    enabled: !!loopsClient && !!loopId,
    staleTime: 15_000,
    meta: AUTH_SCOPED_QUERY_META,
  });
}
