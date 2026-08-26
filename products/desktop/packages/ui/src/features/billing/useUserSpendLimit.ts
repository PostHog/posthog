import type { UserSpendLimit } from "@posthog/api-client/spend-limit";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { AUTH_SCOPED_QUERY_META } from "@posthog/ui/features/auth/useCurrentUser";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

export const USER_SPEND_LIMIT_FLAG = "ai-gateway-user-spend-limit";

export const USER_SPEND_LIMIT_QUERY_KEY = [
  "billing",
  "user-spend-limit",
] as const;

/** The stop line the gateway holds, which is what actually refuses spend. */
export function useUserSpendLimit() {
  const client = useOptionalAuthenticatedClient();
  const enabled = useFeatureFlag(USER_SPEND_LIMIT_FLAG);
  return useQuery({
    queryKey: USER_SPEND_LIMIT_QUERY_KEY,
    queryFn: () => {
      if (!client) throw new Error("Not authenticated");
      return client.getUserSpendLimit();
    },
    // This endpoint can arrive independently of Desktop. Do not request it
    // until its production deployment has been verified.
    enabled: client !== null && enabled,
    staleTime: 60_000,
    retry: false,
    // The stop limit is per user: drop it on any auth transition so a new
    // account never reads the previous one's line from this shared key.
    meta: AUTH_SCOPED_QUERY_META,
  });
}

/**
 * Writes the stop line to the gateway. Null clears it. The query cache takes
 * the response, so the card reflects the limit that is actually held
 * rather than the one that was requested.
 */
export function useSetUserSpendLimit() {
  const client = useOptionalAuthenticatedClient();
  const enabled = useFeatureFlag(USER_SPEND_LIMIT_FLAG);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: {
      limitUsd: number | null;
      windowSeconds: number;
    }): Promise<UserSpendLimit> => {
      if (!client) throw new Error("Not authenticated");
      if (!enabled) {
        return Promise.resolve({
          available: false,
          limitUsd: null,
          windowSeconds: null,
        });
      }
      return input.limitUsd === null
        ? client.clearUserSpendLimit()
        : client.setUserSpendLimit(input.limitUsd, input.windowSeconds);
    },
    onSuccess: (limit) =>
      queryClient.setQueryData(USER_SPEND_LIMIT_QUERY_KEY, limit),
  });
}

/** Whether this deployment can hold a stop line. False while loading or on error. */
export function useSpendLimitAvailable(): boolean {
  const limit = useUserSpendLimit();
  return limit.data?.available === true;
}
