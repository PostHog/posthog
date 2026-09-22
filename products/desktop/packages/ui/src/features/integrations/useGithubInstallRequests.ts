import { hasPendingInstallRequest } from "@posthog/core/integrations/installRequests";
import { githubInstallRequestKeys } from "@posthog/core/integrations/repositoryKeys";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";

export const GITHUB_INSTALL_REQUESTS_QUERY_KEY =
  githubInstallRequestKeys.list();

const PENDING_POLL_INTERVAL_MS = 15_000;

/**
 * Installs waiting on a GitHub org owner. GitHub only reports the outcome through a webhook,
 * so while any request is pending the list is polled; once nothing is pending it goes quiet.
 */
export function useGithubInstallRequests() {
  return useAuthenticatedQuery(
    GITHUB_INSTALL_REQUESTS_QUERY_KEY,
    (client) => client.getGithubInstallRequests(),
    {
      refetchInterval: (query) =>
        hasPendingInstallRequest(query.state.data?.results)
          ? PENDING_POLL_INTERVAL_MS
          : false,
      refetchOnWindowFocus: true,
    },
  );
}
