import { NotAuthenticatedError } from "@posthog/shared";
import { getAuthenticatedClient } from "@posthog/ui/features/auth/authClientImperative";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

export interface BabysitAttention {
  pr_url?: string;
  pr_state?: string;
  head_sha?: string;
  attention?: Record<string, unknown>;
}

/**
 * Poll a run's staged babysit attention (ask mode). The workflow stages PR
 * attention and waits for consent; this hook reads it so the banner can show
 * what needs fixing. Returns null when nothing is waiting or the run is not
 * in ask mode.
 */
export function useBabysitAttention(
  taskId: string | undefined,
  runId: string | undefined,
) {
  const enabled = Boolean(taskId && runId);

  return useQuery<BabysitAttention | null>({
    queryKey: ["babysit-attention", taskId, runId],
    queryFn: async () => {
      const client = await getAuthenticatedClient();
      if (!client) throw new NotAuthenticatedError();
      if (!taskId || !runId) return null;
      return await client.getBabysitAttention(taskId, runId);
    },
    enabled,
    // The workflow parks and waits, so poll while the view is open. A pending
    // attention appears as soon as the workflow stages it; once approved the
    // query returns null and the banner disappears.
    refetchInterval: enabled ? 5_000 : false,
    staleTime: 5_000,
    placeholderData: (prev) => prev,
    retry: 1,
  });
}

/**
 * Approve a staged babysit wake-up so the agent fixes failing checks and
 * review comments. Only meaningful in ask mode.
 */
export function useApproveBabysit(
  taskId: string | undefined,
  runId: string | undefined,
) {
  const queryClient = useQueryClient();

  const mutate = useCallback(async () => {
    const client = await getAuthenticatedClient();
    if (!client) throw new NotAuthenticatedError();
    if (!taskId || !runId) return;
    await client.approveBabysit(taskId, runId);
    await queryClient.invalidateQueries({
      queryKey: ["babysit-attention", taskId, runId],
    });
  }, [taskId, runId, queryClient]);

  return useMutation({ mutationFn: mutate });
}
