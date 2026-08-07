import type { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import { getAuthIdentity } from "@posthog/core/auth/authIdentity";
import { useQuery } from "@tanstack/react-query";
import { useAuthStateValue } from "./store";

export const AUTH_SCOPED_QUERY_META = {
  authScoped: true,
} as const;

export const authKeys = {
  currentUsers: () => ["auth", "current-user"] as const,
  currentUser: (identity: string | null) =>
    [...authKeys.currentUsers(), identity ?? "anonymous"] as const,
};

export function useCurrentUser(options?: {
  enabled?: boolean;
  client?: PostHogAPIClient | null;
  refetchOnWindowFocus?: boolean | "always";
}) {
  const authState = useAuthStateValue((state) => state);
  const client = options?.client ?? null;
  const authIdentity = getAuthIdentity(authState);

  return useQuery({
    queryKey: authKeys.currentUser(authIdentity),
    queryFn: async () => {
      if (!client) {
        throw new Error("Not authenticated");
      }

      return await client.getCurrentUser();
    },
    enabled: !!client && !!authIdentity && (options?.enabled ?? true),
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: options?.refetchOnWindowFocus,
    meta: AUTH_SCOPED_QUERY_META,
  });
}
