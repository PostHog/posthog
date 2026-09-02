import { type DocSchemas, retrieveContextDoc } from "@posthog/api-client/docs";
import { AUTH_SCOPED_QUERY_META } from "@posthog/ui/features/auth/useCurrentUser";
import { useQuery } from "@tanstack/react-query";
import { docsKeys } from "./docsKeys";
import { useDocsClient } from "./useDocsClient";

/** The space's context notes as a doc. The server makes it on the first ask. */
export function useSpaceContextDoc(channelId: string) {
  const docsClient = useDocsClient();
  return useQuery({
    queryKey: docsKeys.contextDoc(docsClient?.projectId ?? null, channelId),
    queryFn: async (): Promise<DocSchemas.Doc> => {
      if (!docsClient) throw new Error("Not authenticated");
      return retrieveContextDoc(
        docsClient.client,
        docsClient.projectId,
        channelId,
      );
    },
    enabled: !!docsClient && !!channelId,
    staleTime: Number.POSITIVE_INFINITY,
    meta: AUTH_SCOPED_QUERY_META,
  });
}
