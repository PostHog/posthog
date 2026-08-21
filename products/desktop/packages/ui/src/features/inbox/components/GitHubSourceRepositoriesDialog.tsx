import type { ExternalDataSource } from "@posthog/api-client/posthog-client";
import {
  buildGithubRepositoriesPatch,
  effectiveGithubSourceRepos,
} from "@posthog/core/integrations/githubSourceRepos";
import {
  Button,
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Text,
} from "@posthog/quill";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { GitHubRepoMultiPicker } from "@posthog/ui/features/folder-picker/GitHubRepoMultiPicker";
import {
  useGithubRepositories,
  useRepositoryIntegration,
} from "@posthog/ui/features/integrations/useIntegrations";
import { toast } from "@posthog/ui/primitives/toast";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

interface GitHubSourceRepositoriesDialogProps {
  source: ExternalDataSource;
  open: boolean;
  onClose: () => void;
  onSaved?: () => void;
}

/**
 * Add or remove repositories on an existing GitHub inbox source. The backend reconciles the
 * per-repo schemas and webhooks from the new list, so the PATCH only carries `repositories`.
 */
export function GitHubSourceRepositoriesDialog({
  source,
  open,
  onClose,
  onSaved,
}: GitHubSourceRepositoriesDialogProps) {
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  const client = useOptionalAuthenticatedClient();
  const queryClient = useQueryClient();
  const initialRepos = effectiveGithubSourceRepos(source.job_inputs);
  const [repos, setRepos] = useState<string[]>(initialRepos);
  const [searchQuery, setSearchQuery] = useState("");
  const [pickerOpen, setPickerOpen] = useState(false);
  const { repositories, isLoadingRepos, getIntegrationIdForRepo } =
    useRepositoryIntegration();
  // A source syncs through one GitHub installation, and editing repos can't change it. Scope the
  // picker to that installation so it never offers repos the source's credential can't reach; the
  // source's stored repos all resolve to the same integration, so the first one identifies it.
  const sourceIntegrationId = initialRepos[0]
    ? getIntegrationIdForRepo(initialRepos[0])
    : undefined;
  const {
    repositories: visibleRepositories,
    isPending: visibleRepositoriesLoading,
    isFetchingMore,
    hasMore,
    loadMore,
  } = useGithubRepositories(searchQuery, pickerOpen, sourceIntegrationId);

  const save = useMutation({
    mutationFn: async () => {
      if (!client) throw new Error("Not authenticated");
      if (projectId == null) throw new Error("No project selected");
      await client.updateExternalDataSource(
        projectId,
        source.id,
        buildGithubRepositoriesPatch(repos),
      );
    },
    onSuccess: () => {
      toast.success("Repositories updated");
      void queryClient.invalidateQueries({
        queryKey: ["external-data-sources", projectId],
      });
      onSaved?.();
      onClose();
    },
    onError: (error) => {
      toast.error(
        error instanceof Error
          ? error.message
          : "Failed to update repositories",
      );
    },
  });

  const unchanged =
    repos.length === initialRepos.length &&
    repos.every((repo) => initialRepos.includes(repo));

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next && !save.isPending) onClose();
      }}
    >
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Edit repositories</DialogTitle>
          <DialogDescription>
            Issues from these repositories feed Self-driving. Removing one stops
            syncing it; its past signals stay.
          </DialogDescription>
        </DialogHeader>
        <DialogBody>
          <div className="flex flex-col gap-2">
            <GitHubRepoMultiPicker
              value={repos}
              onChange={setRepos}
              repositories={pickerOpen ? visibleRepositories : repositories}
              isLoading={
                isLoadingRepos || (pickerOpen && visibleRepositoriesLoading)
              }
              isLoadingMore={isFetchingMore}
              hasMore={hasMore}
              onLoadMore={loadMore}
              open={pickerOpen}
              onOpenChange={(next) => {
                setPickerOpen(next);
                if (!next) setSearchQuery("");
              }}
              searchQuery={searchQuery}
              onSearchQueryChange={setSearchQuery}
              disabled={save.isPending}
            />
            {repos.length === 0 ? (
              <Text size="xs" className="text-(--amber-11)">
                Keep at least one repository, or turn the source off instead.
              </Text>
            ) : null}
          </div>
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={save.isPending}>
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={() => save.mutate()}
            loading={save.isPending}
            disabled={save.isPending || repos.length === 0 || unchanged}
          >
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
