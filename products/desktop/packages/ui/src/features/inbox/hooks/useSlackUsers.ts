import type {
  SlackMembersQueryParams,
  SlackMembersResponse,
} from "@posthog/shared/domain-types";
import { useAuthenticatedQuery } from "../../../hooks/useAuthenticatedQuery";

const DEFAULT_MEMBER_PAGE_SIZE = 50;

export interface UseSlackUsersOptions extends SlackMembersQueryParams {
  enabled?: boolean;
}

export function useSlackUsers(
  integrationId: number | null | undefined,
  options?: UseSlackUsersOptions,
) {
  const {
    search,
    limit = DEFAULT_MEMBER_PAGE_SIZE,
    offset,
    userId,
    enabled = true,
  } = options ?? {};
  const normalizedSearch = search?.trim() || undefined;

  return useAuthenticatedQuery<SlackMembersResponse>(
    [
      "slack",
      "users",
      integrationId ?? null,
      normalizedSearch ?? "",
      limit,
      offset ?? 0,
      userId ?? null,
    ],
    async (client) => {
      if (!integrationId) {
        return { users: [] };
      }
      return await client.getSlackUsersForIntegration(integrationId, {
        search: normalizedSearch,
        limit,
        offset,
        userId,
      });
    },
    {
      enabled: !!integrationId && enabled,
      refetchOnWindowFocus: false,
      // Full member lists are cached server-side for an hour; search pages
      // refresh sooner.
      staleTime: normalizedSearch || userId ? 30_000 : 5 * 60_000,
    },
  );
}
