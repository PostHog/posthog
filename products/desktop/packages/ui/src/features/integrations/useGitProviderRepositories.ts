import type { GitProviderService } from "@posthog/core/integrations/gitProviderService";
import { enabledGitProviders } from "@posthog/core/integrations/gitProviders";
import { GIT_PROVIDER_SERVICE } from "@posthog/core/integrations/identifiers";
import { useService } from "@posthog/di/react";
import { GITLAB_INTEGRATION_FLAG } from "@posthog/shared";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import {
  useGithubRepositoryQueries,
  useIntegrations,
} from "@posthog/ui/features/integrations/useIntegrations";
import { useMutation, useQueryClient } from "@tanstack/react-query";

export function useGitProviderRepositories() {
  const gitlabEnabled = useFeatureFlag(GITLAB_INTEGRATION_FLAG);
  const providers = enabledGitProviders({ gitlabEnabled });
  const integrationQuery = useIntegrations();
  const integrations = integrationQuery.data ?? [];
  const githubQueries = useGithubRepositoryQueries(
    integrations.filter((integration) => integration.kind === "github"),
  );
  const service = useService<GitProviderService>(GIT_PROVIDER_SERVICE);
  const queryClient = useQueryClient();
  const data = service.combineRepositories(
    integrations,
    providers,
    githubQueries,
  );
  const refresh = useMutation({
    mutationFn: async () => {
      const result = await integrationQuery.refetch({ throwOnError: true });
      const { keys, errors } = await service.refreshRepositories(
        result.data ?? [],
      );
      await Promise.all(
        keys.map(({ queryKey, exact }) =>
          queryClient.invalidateQueries({ queryKey, exact }),
        ),
      );
      if (errors.length > 0) {
        throw new AggregateError(
          errors,
          "Failed to refresh repository connections",
        );
      }
    },
  });

  return {
    data,
    isPending:
      integrationQuery.isPending ||
      (data.repositories.length === 0 && data.pendingConnections.length > 0),
    isError:
      (integrationQuery.isError || refresh.isError) &&
      data.repositories.length === 0,
    hasRefreshError: refresh.isError || integrationQuery.isError,
    isRefetching:
      refresh.isPending ||
      integrationQuery.isFetching ||
      githubQueries.some((query) => query.isFetching),
    refetch: () => refresh.mutate(),
  };
}
