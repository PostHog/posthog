import { type DocSchemas, retrieveSpaceHome } from "@posthog/api-client/docs";
import { AUTH_SCOPED_QUERY_META } from "@posthog/ui/features/auth/useCurrentUser";
import { useQuery } from "@tanstack/react-query";
import { docsKeys } from "./docsKeys";
import { useDocsClient } from "./useDocsClient";

/** What the space's docs home renders: every doc in the space, in tab order. */
export function useSpaceHome(channelId: string) {
  const docsClient = useDocsClient();
  return useQuery({
    queryKey: docsKeys.home(docsClient?.projectId ?? null, channelId),
    queryFn: async (): Promise<DocSchemas.SpaceHome> => {
      if (!docsClient) throw new Error("Not authenticated");
      return retrieveSpaceHome(
        docsClient.client,
        docsClient.projectId,
        channelId,
      );
    },
    enabled: !!docsClient && !!channelId,
    // Short: reports and counts change while a person is away on a page.
    staleTime: 5_000,
    meta: AUTH_SCOPED_QUERY_META,
  });
}
