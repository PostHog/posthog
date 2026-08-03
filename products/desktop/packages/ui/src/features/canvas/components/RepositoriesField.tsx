import { GithubLogoIcon, XIcon } from "@phosphor-icons/react";
import {
  Input,
  Popover,
  PopoverContent,
  PopoverTrigger,
  Button as QuillButton,
} from "@posthog/quill";
import { useRepositoryIntegration } from "@posthog/ui/features/integrations/useIntegrations";
import { Tooltip } from "@posthog/ui/primitives/Tooltip";
import { Flex, Spinner } from "@radix-ui/themes";
import { useState } from "react";

export const MAX_REPOSITORIES = 10;

const REPO_SEARCH_THRESHOLD = 10;

function RepoChip({
  repository,
  onRemove,
}: {
  repository: string;
  onRemove: () => void;
}) {
  return (
    <span className="group/chip inline-flex h-6 items-center gap-1.5 rounded-md bg-(--gray-a3) pr-2.5 pl-2 font-medium text-(--gray-11) text-[12px] transition-colors hover:bg-(--gray-a4)">
      <button
        type="button"
        aria-label={`Remove ${repository}`}
        className="relative inline-flex size-4 shrink-0 cursor-pointer items-center justify-center border-none bg-transparent p-0"
        onClick={onRemove}
      >
        <span className="pointer-events-none absolute inset-0 flex items-center justify-center opacity-100 transition-opacity duration-150 group-hover/chip:opacity-0 motion-reduce:transition-none">
          <GithubLogoIcon size={14} />
        </span>
        <span className="pointer-events-none absolute inset-0 flex items-center justify-center opacity-0 transition-opacity duration-150 group-hover/chip:opacity-100 motion-reduce:transition-none">
          <XIcon size={13} weight="bold" />
        </span>
      </button>
      <span className="max-w-[200px] truncate">{repository}</span>
    </span>
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
          <QuillButton variant="outline" size="sm">
            <GithubLogoIcon size={14} />
            {label}
          </QuillButton>
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
              <button
                key={repository}
                type="button"
                onClick={() => {
                  onAdd(repository);
                  setOpen(false);
                }}
                className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left text-[13px] hover:bg-[var(--fill-hover)]"
              >
                <GithubLogoIcon size={14} className="shrink-0" />
                <span className="truncate">{repository}</span>
              </button>
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
    // Radix spacing tokens are unavailable inside the dialog portal.
    <Flex align="center" wrap="wrap" className="min-h-7 w-fit max-w-full gap-2">
      {selected.map((repository) => (
        <RepoChip
          key={repository}
          repository={repository}
          onRemove={() => removeRepository(repository)}
        />
      ))}

      {disabled ? (
        <QuillButton variant="outline" size="sm" disabled>
          <GithubLogoIcon size={14} />
          Add repository
        </QuillButton>
      ) : isLoadingList && hasGithubIntegration ? (
        <QuillButton variant="outline" size="sm" disabled>
          <Spinner size="1" />
          Loading repositories…
        </QuillButton>
      ) : addDisabledReason ? (
        <Tooltip content={addDisabledReason}>
          <span className="inline-flex">
            <QuillButton variant="outline" size="sm" disabled>
              <GithubLogoIcon size={14} />
              Add repository
            </QuillButton>
          </span>
        </Tooltip>
      ) : (
        <AddRepositoryPopover
          available={available}
          onAdd={addRepository}
          label={selected.length > 0 ? "Add…" : "Add repository…"}
        />
      )}
    </Flex>
  );
}
