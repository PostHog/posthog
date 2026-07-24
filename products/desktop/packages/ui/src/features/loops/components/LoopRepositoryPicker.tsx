import type { LoopSchemas } from "@posthog/api-client/loops";
import { GitHubRepoPicker } from "@posthog/ui/features/folder-picker/GitHubRepoPicker";
import { useRepositoryIntegration } from "@posthog/ui/features/integrations/useIntegrations";

interface LoopRepositoryPickerProps {
  value: LoopSchemas.LoopRepositoryEntry | null;
  onChange: (repo: LoopSchemas.LoopRepositoryEntry | null) => void;
  disabled?: boolean;
}

/**
 * Loops run against the team's connected GitHub App installations, not the
 * viewer's personal repo list, so this uses `useRepositoryIntegration`
 * (team-scoped) rather than `useUserRepositoryIntegration` (used by the task
 * composer). A repo without a resolvable integration id is ignored, which
 * only happens mid-refresh, before the repository map has caught up.
 */
export function LoopRepositoryPicker({
  value,
  onChange,
  disabled,
}: LoopRepositoryPickerProps) {
  const {
    repositories,
    getIntegrationIdForRepo,
    isLoadingRepos,
    isRefreshingRepos,
    refreshRepositories,
    hasGithubIntegration,
  } = useRepositoryIntegration();

  const handleChange = (repo: string | null) => {
    if (!repo) {
      onChange(null);
      return;
    }
    const integrationId = getIntegrationIdForRepo(repo);
    if (integrationId == null) {
      onChange(null);
      return;
    }
    onChange({ github_integration_id: integrationId, full_name: repo });
  };

  return (
    <GitHubRepoPicker
      value={value?.full_name ?? null}
      onChange={handleChange}
      repositories={repositories}
      isLoading={isLoadingRepos}
      isRefreshing={isRefreshingRepos}
      onRefresh={() => void refreshRepositories()}
      placeholder="Select repository…"
      size="2"
      disabled={disabled || !hasGithubIntegration}
    />
  );
}
