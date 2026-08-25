import type { UserSpendLimit } from "@posthog/api-client/spend-limit";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

export const USER_SPEND_LIMIT_QUERY_KEY = [
  "billing",
  "user-spend-limit",
] as const;

/** The stop line the gateway holds, which is what actually refuses spend. */
export function useUserSpendLimit() {
  const client = useOptionalAuthenticatedClient();
  return useQuery({
    queryKey: USER_SPEND_LIMIT_QUERY_KEY,
    queryFn: () => {
      if (!client) throw new Error("Not authenticated");
      return client.getUserSpendLimit();
    },
    enabled: client !== null,
    staleTime: 60_000,
    retry: false,
  });
}

/**
 * Writes the stop line to the gateway. Null clears it. The query cache takes
 * the response, so the card reflects the limit that is actually enforced
 * rather than the one that was requested.
 */
export function useSetUserSpendLimit() {
  const client = useOptionalAuthenticatedClient();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: {
      limitUsd: number | null;
      windowSeconds: number;
    }): Promise<UserSpendLimit> => {
      if (!client) throw new Error("Not authenticated");
      return input.limitUsd === null
        ? client.clearUserSpendLimit()
        : client.setUserSpendLimit(input.limitUsd, input.windowSeconds);
    },
    onSuccess: (limit) =>
      queryClient.setQueryData(USER_SPEND_LIMIT_QUERY_KEY, limit),
  });
}
