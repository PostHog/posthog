import {
  useUserGithubRepositories,
  useUserRepositoryIntegration,
} from "@posthog/ui/features/integrations/useIntegrations";
import { toast } from "@posthog/ui/primitives/toast";
import { useCallback, useState } from "react";

export function useCloudRepoPicker() {
  const {
    repositories,
    isLoadingRepos,
    isRefreshingRepos,
    refreshRepositories,
  } = useUserRepositoryIntegration();
  const [isOpen, setIsOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const {
    repositories: visibleCloudRepositories,
    isPending: cloudRepositoriesLoading,
    hasMore,
    loadMore,
  } = useUserGithubRepositories(searchQuery, isOpen);

  const handleOpenChange = useCallback((open: boolean) => {
    setIsOpen(open);
    if (!open) {
      setSearchQuery("");
    }
  }, []);

  const handleRefresh = useCallback(() => {
    void refreshRepositories().catch((error) => {
      toast.error("Failed to refresh repositories", {
        description:
          error instanceof Error ? error.message : "Please try again.",
      });
    });
  }, [refreshRepositories]);

  return {
    repositories: isOpen ? visibleCloudRepositories : repositories,
    isLoading: isLoadingRepos || (isOpen && cloudRepositoriesLoading),
    isRefreshing: isRefreshingRepos,
    onRefresh: handleRefresh,
    open: isOpen,
    onOpenChange: handleOpenChange,
    searchQuery,
    onSearchQueryChange: setSearchQuery,
    hasMore,
    onLoadMore: loadMore,
  };
}
