import { GithubLogoIcon, XIcon } from "@phosphor-icons/react";
import {
  Button,
  Chip,
  ChipClose,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { GitHubRepoPicker } from "@posthog/ui/features/folder-picker/GitHubRepoPicker";
import { useIntegrationSelectors } from "@posthog/ui/features/integrations/store";
import { useGithubRepositories } from "@posthog/ui/features/integrations/useIntegrations";
import { useState } from "react";

export const MAX_REPOSITORIES = 10;

function RepoChip({
  repository,
  onRemove,
  disabled,
}: {
  repository: string;
  onRemove: () => void;
  disabled: boolean;
}) {
  return (
    <Chip>
      <GithubLogoIcon size={14} />
      <span className="max-w-[200px] truncate">{repository}</span>
      <ChipClose
        aria-label={`Remove ${repository}`}
        disabled={disabled}
        onClick={onRemove}
      >
        <XIcon size={13} weight="bold" />
      </ChipClose>
    </Chip>
  );
}

function AddRepositoryPopover({
  selected,
  integrationId,
  onAdd,
  label,
}: {
  selected: string[];
  integrationId: number | null;
  onAdd: (repository: string, integrationId: number) => void;
  label: string;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const {
    repositories,
    getIntegrationIdForRepo,
    isPending,
    isFetchingMore,
    hasMore,
    loadMore,
  } = useGithubRepositories(query, true, integrationId);
  const available = repositories.filter(
    (repository) => !selected.includes(repository),
  );

  return (
    <GitHubRepoPicker
      value={null}
      repositories={available}
      isLoading={isPending}
      isLoadingMore={isFetchingMore}
      placeholder={label}
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) setQuery("");
      }}
      searchQuery={query}
      onSearchQueryChange={setQuery}
      hasMore={hasMore}
      onLoadMore={loadMore}
      onChange={(repository) => {
        if (!repository) return;
        const repositoryIntegrationId = getIntegrationIdForRepo(repository);
        if (repositoryIntegrationId == null) return;
        onAdd(repository, repositoryIntegrationId);
        setOpen(false);
      }}
    />
  );
}

interface RepositoriesFieldProps {
  selected: string[];
  integrationId: number | null;
  onChange: (repositories: string[], integrationId: number | null) => void;
  disabled?: boolean;
  /** Caps the list, e.g. an image spec that builds for one repository. */
  max?: number;
  /** Why no more can be added, shown on the disabled add button. */
  maxReason?: string;
}

export function RepositoriesField({
  selected,
  integrationId,
  onChange,
  disabled = false,
  max = MAX_REPOSITORIES,
  maxReason,
}: RepositoriesFieldProps) {
  const { hasGithubIntegration } = useIntegrationSelectors();

  const atLimit = selected.length >= max;

  const addRepository = (
    repository: string,
    repositoryIntegrationId: number,
  ) => {
    if (disabled || selected.includes(repository)) return;
    onChange([...selected, repository], repositoryIntegrationId);
  };

  const removeRepository = (repository: string) => {
    if (disabled) return;
    const next = selected.filter((item) => item !== repository);
    onChange(next, next.length === 0 ? null : integrationId);
  };

  const addDisabledReason = !hasGithubIntegration
    ? "Connect GitHub in settings to add repositories"
    : atLimit
      ? (maxReason ?? `You can add up to ${max} repositories`)
      : null;

  return (
    <div className="flex min-h-7 w-fit max-w-full flex-wrap items-center gap-2">
      {selected.map((repository) => (
        <RepoChip
          key={repository}
          repository={repository}
          disabled={disabled}
          onRemove={() => removeRepository(repository)}
        />
      ))}

      {disabled ? (
        <Button variant="outline" size="sm" disabled>
          <GithubLogoIcon size={14} />
          Add repository
        </Button>
      ) : addDisabledReason ? (
        <Tooltip>
          <TooltipTrigger
            render={
              <span className="inline-flex">
                <Button variant="outline" size="sm" disabled>
                  <GithubLogoIcon size={14} />
                  Add repository
                </Button>
              </span>
            }
          />
          <TooltipContent>{addDisabledReason}</TooltipContent>
        </Tooltip>
      ) : (
        <AddRepositoryPopover
          selected={selected}
          integrationId={integrationId}
          onAdd={addRepository}
          label={selected.length > 0 ? "Add…" : "Add repository…"}
        />
      )}
    </div>
  );
}
