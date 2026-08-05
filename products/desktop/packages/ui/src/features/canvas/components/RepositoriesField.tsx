import { GithubLogoIcon, XIcon } from "@phosphor-icons/react";
import {
  Button,
  Chip,
  ChipClose,
  Input,
  ItemContent,
  ItemMedia,
  ItemMenuItem,
  ItemTitle,
  Popover,
  PopoverContent,
  PopoverTrigger,
  Spinner,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { useRepositoryIntegration } from "@posthog/ui/features/integrations/useIntegrations";
import { useState } from "react";

export const MAX_REPOSITORIES = 10;

const REPO_SEARCH_THRESHOLD = 10;

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
  available,
  onAdd,
  label,
}: {
  available: string[];
  onAdd: (repository: string) => void;
  label: string;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");

  const showSearch = available.length > REPO_SEARCH_THRESHOLD;
  const trimmed = query.trim().toLowerCase();
  const filtered = trimmed
    ? available.filter((repository) =>
        repository.toLowerCase().includes(trimmed),
      )
    : available;

  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) setQuery("");
      }}
    >
      <PopoverTrigger
        render={
          <Button variant="outline" size="sm">
            <GithubLogoIcon size={14} />
            {label}
          </Button>
        }
      />
      <PopoverContent
        align="start"
        sideOffset={6}
        className="flex max-h-72 w-64 flex-col p-0"
      >
        {showSearch ? (
          <div className="shrink-0 border-gray-5 border-b p-1.5">
            <Input
              autoFocus
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search repositories…"
              className="h-7"
            />
          </div>
        ) : null}
        <div className="min-h-0 flex-1 overflow-y-auto p-1">
          {filtered.length === 0 ? (
            <div className="px-2 py-1.5 text-[13px] text-gray-10">
              No repositories found
            </div>
          ) : (
            filtered.map((repository) => (
              <ItemMenuItem
                key={repository}
                size="xs"
                onClick={() => {
                  onAdd(repository);
                  setOpen(false);
                }}
              >
                <ItemMedia variant="icon">
                  <GithubLogoIcon size={14} />
                </ItemMedia>
                <ItemContent variant="menuItem">
                  <ItemTitle className="truncate">{repository}</ItemTitle>
                </ItemContent>
              </ItemMenuItem>
            ))
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}

interface RepositoriesFieldProps {
  selected: string[];
  integrationId: number | null;
  onChange: (repositories: string[], integrationId: number | null) => void;
  disabled?: boolean;
}

export function RepositoriesField({
  selected,
  integrationId,
  onChange,
  disabled = false,
}: RepositoriesFieldProps) {
  const {
    repositories,
    getIntegrationIdForRepo,
    isLoadingRepos,
    hasGithubIntegration,
  } = useRepositoryIntegration();

  const atLimit = selected.length >= MAX_REPOSITORIES;
  const available = repositories.filter((repository) => {
    const repositoryIntegration = getIntegrationIdForRepo(repository);
    return (
      !selected.includes(repository) &&
      repositoryIntegration != null &&
      (integrationId === null || repositoryIntegration === integrationId)
    );
  });

  const addRepository = (repository: string) => {
    if (disabled || selected.includes(repository)) return;
    const repositoryIntegration = getIntegrationIdForRepo(repository);
    if (repositoryIntegration == null) return;
    onChange([...selected, repository], repositoryIntegration);
  };

  const removeRepository = (repository: string) => {
    if (disabled) return;
    const next = selected.filter((item) => item !== repository);
    onChange(next, next.length === 0 ? null : integrationId);
  };

  const isLoadingList = isLoadingRepos && available.length === 0;
  const addDisabledReason = !hasGithubIntegration
    ? "Connect GitHub in settings to add repositories"
    : atLimit
      ? `You can add up to ${MAX_REPOSITORIES} repositories`
      : available.length === 0
        ? selected.length > 0
          ? "All accessible repositories are already added"
          : "No repositories available"
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
      ) : isLoadingList && hasGithubIntegration ? (
        <Button variant="outline" size="sm" disabled>
          <Spinner className="size-3.5" />
          Loading repositories…
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
          available={available}
          onAdd={addRepository}
          label={selected.length > 0 ? "Add…" : "Add repository…"}
        />
      )}
    </div>
  );
}
