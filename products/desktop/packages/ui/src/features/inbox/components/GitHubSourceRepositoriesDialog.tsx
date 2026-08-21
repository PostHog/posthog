import type { ExternalDataSource } from "@posthog/api-client/posthog-client";
import {
  buildGithubRepositoriesPatch,
  effectiveGithubSourceRepos,
  GITHUB_ISSUES_SYNC_TYPE,
  githubIssuesSchemasToEnable,
  githubSourceIntegrationId,
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
 * per-repo schemas and webhooks from the new list, so the PATCH only carries `repositories`; it
 * creates an added repository's rows disabled, which the save then switches on.
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
  const { repositories, isLoadingRepos } = useRepositoryIntegration();
  // A source syncs through one GitHub installation, and editing repos can't change it. Scope the
  // picker to the installation the source stored, so it never offers repos the source's credential
  // can't reach. Null on a personal-access-token source, which has no installation to scope by.
  const sourceIntegrationId = githubSourceIntegrationId(source.job_inputs);
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
      // Saving the list creates each added repository's rows disabled, so read the source back
      // and switch its issues on — otherwise the repository shows on the card and syncs nothing.
      const saved = (await client.listExternalDataSources(projectId)).find(
        (candidate) => candidate.id === source.id,
      );
      for (const schema of githubIssuesSchemasToEnable(repos, saved)) {
        await client.updateExternalDataSchema(projectId, schema.id, {
          should_sync: true,
          sync_type: GITHUB_ISSUES_SYNC_TYPE,
        });
      }
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

  const initialRepoSet = new Set(initialRepos);
  const unchanged =
    repos.length === initialRepoSet.size &&
    repos.every((repo) => initialRepoSet.has(repo));
  // A save reconciles the repositories first, then switches their issues schemas on in a second
  // step. If that step fails, the repositories PATCH has already landed, so once the source
  // refetches the list is unchanged yet some schemas are still off. Keep Save usable in that
  // case so a retry can finish enabling them.
  const hasSchemasToEnable =
    githubIssuesSchemasToEnable(repos, source).length > 0;

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
            disabled={
              save.isPending ||
              repos.length === 0 ||
              (unchanged && !hasSchemasToEnable)
            }
          >
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
