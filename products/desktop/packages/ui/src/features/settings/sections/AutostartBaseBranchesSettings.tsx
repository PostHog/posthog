import { X } from "@phosphor-icons/react";
import { Button } from "@posthog/quill";
import { GitHubRepoPicker } from "@posthog/ui/features/folder-picker/GitHubRepoPicker";
import { BranchSelector } from "@posthog/ui/features/git-interaction/components/BranchSelector";
import {
  useGithubBranches,
  useGithubRepositories,
  useRepositoryIntegration,
} from "@posthog/ui/features/integrations/useIntegrations";
import { Box, Flex, IconButton, Text } from "@radix-ui/themes";
import { useState } from "react";

interface AutostartBaseBranchesSettingsProps {
  /** Current `org/repo` → base branch overrides. */
  branches: Record<string, string>;
  /** Persist the full next mapping (the caller diffs/optimistically updates). */
  onChange: (next: Record<string, string>) => void;
  isLoading?: boolean;
}

/**
 * Per-repository base branch overrides for auto-started inbox PRs.
 *
 * Each configured repo opens its auto-PRs against the chosen branch instead of
 * the repo default. Repos without an entry keep targeting the repo default
 */
export function AutostartBaseBranchesSettings({
  branches,
  onChange,
  isLoading = false,
}: AutostartBaseBranchesSettingsProps) {
  const {
    repositories: allRepositories,
    getIntegrationIdForRepo,
    isLoadingRepos,
    isRefreshingRepos,
    refreshRepositories,
    hasGithubIntegration,
  } = useRepositoryIntegration();
  const disabled = !hasGithubIntegration;

  const [isRepoPickerOpen, setIsRepoPickerOpen] = useState(false);
  const [repoSearch, setRepoSearch] = useState("");
  const [pendingRepo, setPendingRepo] = useState<string | null>(null);

  const repoPage = useGithubRepositories(repoSearch, isRepoPickerOpen);

  const selectableRepositories = (
    isRepoPickerOpen ? repoPage.repositories : allRepositories
  ).filter((repo) => !(repo in branches));

  const entries = Object.entries(branches);

  const commit = (repo: string, branch: string) => {
    onChange({ ...branches, [repo]: branch });
  };

  const remove = (repo: string) => {
    const next = { ...branches };
    delete next[repo];
    onChange(next);
  };

  return (
    <Flex
      direction="column"
      gap="2"
      pt="3"
      style={{ borderTop: "1px dashed var(--gray-5)" }}
    >
      <Flex direction="column" gap="1">
        <Text className="font-medium text-(--gray-12) text-sm">
          Base branch for auto-PRs
        </Text>
        <Text className="text-(--gray-11) text-[13px]">
          Point auto-started inbox PRs at a specific branch per repository.
          Repositories without an override target their default branch.
        </Text>
      </Flex>

      {isLoading ? (
        <Box className="h-[32px] w-[320px] animate-pulse rounded bg-gray-3" />
      ) : (
        <Flex direction="column" gap="2">
          {entries.map(([repo, branch]) => (
            <BaseBranchRow
              key={repo}
              repo={repo}
              value={branch}
              integrationId={getIntegrationIdForRepo(repo)}
              disabled={disabled}
              onCommit={commit}
              onRemove={remove}
            />
          ))}

          <Flex align="center" gap="2">
            <Box className="min-w-[220px] max-w-[280px]">
              <GitHubRepoPicker
                value={pendingRepo}
                onChange={setPendingRepo}
                repositories={selectableRepositories}
                isLoading={
                  isLoadingRepos || (isRepoPickerOpen && repoPage.isPending)
                }
                isRefreshing={isRefreshingRepos}
                onRefresh={refreshRepositories}
                open={isRepoPickerOpen}
                onOpenChange={setIsRepoPickerOpen}
                searchQuery={repoSearch}
                onSearchQueryChange={setRepoSearch}
                hasMore={repoPage.hasMore}
                onLoadMore={repoPage.loadMore}
                disabled={disabled}
                placeholder="Add a repository…"
                size="2"
              />
            </Box>
            {pendingRepo ? (
              <BaseBranchRow
                key={`add-${pendingRepo}`}
                repo={pendingRepo}
                value={undefined}
                integrationId={getIntegrationIdForRepo(pendingRepo)}
                disabled={disabled}
                onCommit={(repo, branch) => {
                  commit(repo, branch);
                  setPendingRepo(null);
                  setRepoSearch("");
                }}
              />
            ) : null}
          </Flex>
        </Flex>
      )}
    </Flex>
  );
}

interface BaseBranchRowProps {
  repo: string;
  value: string | undefined;
  integrationId: number | undefined;
  disabled?: boolean;
  onCommit: (repo: string, branch: string) => void;
  onRemove?: (repo: string) => void;
}

function BaseBranchRow({
  repo,
  value,
  integrationId,
  disabled = false,
  onCommit,
  onRemove,
}: BaseBranchRowProps) {
  const isAdd = value === undefined;
  const [search, setSearch] = useState("");
  const [draft, setDraft] = useState<string | null>(null);

  const branchQuery = useGithubBranches(integrationId, repo, search, true);
  const hasIntegrationId = !!integrationId;

  const selectedBranch = isAdd ? draft : (value ?? null);

  return (
    <Flex align="center" gap="2">
      {!isAdd ? (
        <Text className="min-w-[220px] max-w-[280px] truncate text-(--gray-12) text-sm">
          {repo}
        </Text>
      ) : null}
      <BranchSelector
        repoPath={repo}
        currentBranch={null}
        defaultBranch={branchQuery.data?.defaultBranch ?? null}
        workspaceMode="cloud"
        disabled={disabled || !hasIntegrationId}
        selectedBranch={selectedBranch}
        onBranchSelect={(branch) => {
          if (isAdd) {
            setDraft(branch);
          } else if (branch) {
            onCommit(repo, branch);
          }
        }}
        cloudBranches={branchQuery.data?.branches}
        cloudBranchesLoading={branchQuery.isPending}
        isRefreshing={branchQuery.isRefreshing}
        cloudBranchesFetchingMore={branchQuery.isFetchingMore}
        cloudBranchesHasMore={branchQuery.hasMore}
        cloudSearchQuery={search}
        onCloudSearchChange={setSearch}
        onCloudLoadMore={branchQuery.loadMore}
      />
      {isAdd ? (
        <Button
          size="sm"
          disabled={disabled || !draft}
          onClick={() => {
            if (draft) onCommit(repo, draft);
          }}
        >
          Add
        </Button>
      ) : (
        <IconButton
          variant="ghost"
          color="gray"
          aria-label={`Remove base branch override for ${repo}`}
          disabled={disabled}
          onClick={() => onRemove?.(repo)}
        >
          <X size={14} />
        </IconButton>
      )}
    </Flex>
  );
}
