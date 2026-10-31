import type { GitProviderService } from "@posthog/core/integrations/gitProviderService";
import { enabledGitProviders } from "@posthog/core/integrations/gitProviders";
import { GIT_PROVIDER_SERVICE } from "@posthog/core/integrations/identifiers";
import { integrationKeys } from "@posthog/core/integrations/repositoryKeys";
import { useService } from "@posthog/di/react";
import { GITLAB_INTEGRATION_FLAG } from "@posthog/shared";
import { AUTH_SCOPED_QUERY_META } from "@posthog/ui/features/auth/useCurrentUser";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { useIntegrationStore } from "@posthog/ui/features/integrations/store";
import { useQuery } from "@tanstack/react-query";

/**
 * Every repository the project reaches through its connected source control providers, in one
 * list. GitLab joins the list only while the flag is on; the integrations list itself comes from
 * `useIntegrations()`, which the root route already keeps fresh.
 */
export function useGitProviderRepositories() {
  const gitlabEnabled = useFeatureFlag(GITLAB_INTEGRATION_FLAG);
  const providers = enabledGitProviders({ gitlabEnabled });
  const integrations = useIntegrationStore((state) => state.integrations);
  const service = useService<GitProviderService>(GIT_PROVIDER_SERVICE);

  const integrationIds = integrations.map((integration) => integration.id);

  return useQuery({
    queryKey: [
      ...integrationKeys.all,
      "git-provider-repositories",
      providers,
      integrationIds,
    ],
    queryFn: () => service.listRepositories(integrations, providers),
    staleTime: 5 * 60 * 1000,
    meta: AUTH_SCOPED_QUERY_META,
  });
}
