import type { UserBasic } from "@posthog/shared/domain-types";
import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { useAuthStore } from "@/features/auth";
import { getPostHogApiClient } from "@/lib/posthogApiClient";
import { userDisplayName } from "../utils/userDisplayName";

// Membership churn is slow; one fetch per session window is plenty.
const ORG_MEMBERS_STALE_MS = 5 * 60_000;

export function useOrgMembers(options?: { enabled?: boolean }): {
  members: UserBasic[];
  isLoading: boolean;
} {
  const { projectId, oauthAccessToken } = useAuthStore();

  const query = useQuery({
    queryKey: ["org-members"],
    queryFn: () => getPostHogApiClient().listOrganizationMembersWithStatus(),
    enabled: (options?.enabled ?? true) && !!projectId && !!oauthAccessToken,
    staleTime: ORG_MEMBERS_STALE_MS,
  });

  const members = useMemo(
    () =>
      (query.data?.members ?? [])
        .flatMap((member) => (member.user?.email ? [member.user] : []))
        .sort((a, b) => userDisplayName(a).localeCompare(userDisplayName(b))),
    [query.data],
  );

  return { members, isLoading: query.isLoading };
}
