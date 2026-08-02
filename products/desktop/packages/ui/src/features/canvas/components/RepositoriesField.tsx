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

// Show the filter field only once the list is long enough to warrant scanning.
const REPO_SEARCH_THRESHOLD = 10;

// A single repository, rendered as a subtle tag. The leading GitHub glyph swaps
// to an X on hover so the whole chip is the remove target — no separate delete
// button crowding the tag (mirrors the message editor's attachments).
function RepoChip({
  repository,
  onRemove,
}: {
  repository: string;
  onRemove: () => void;
}) {
  return (
    <span className="group/chip inline-flex items-center gap-1 rounded-(--radius-1) bg-(--gray-a3) py-0.5 pr-2 pl-1.5 font-medium text-(--gray-11) text-[12px] transition-colors hover:bg-(--gray-a4)">
      <button
        type="button"
        aria-label={`Remove ${repository}`}
        className="relative inline-flex size-3.5 shrink-0 cursor-pointer items-center justify-center border-none bg-transparent p-0"
        onClick={onRemove}
      >
        <span className="pointer-events-none absolute inset-0 flex items-center justify-center opacity-100 transition-opacity duration-150 group-hover/chip:opacity-0 motion-reduce:transition-none">
          <GithubLogoIcon size={13} />
        </span>
        <span className="pointer-events-none absolute inset-0 flex items-center justify-center opacity-0 transition-opacity duration-150 group-hover/chip:opacity-100 motion-reduce:transition-none">
          <XIcon size={12} weight="bold" />
        </span>
      </button>
      <span className="max-w-[200px] truncate">{repository}</span>
    </span>
  );
}

// The add-repository picker: a button that opens a popover listing the addable
// repositories. A search field pins to the top once the list is long; only the
// list scrolls, so there's a single scrollbar.
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
  /** Currently linked repositories, `organization/repo` each. */
  selected: string[];
  /** The GitHub integration the selection belongs to, or null when empty. */
  integrationId: number | null;
  /** Fired with the next selection + its integration on every add/remove. */
  onChange: (repositories: string[], integrationId: number | null) => void;
  /** Freeze interaction (e.g. while a create flow is submitting). */
  disabled?: boolean;
}

// Controlled row of repository chips plus an on-demand add picker. The caller
// owns the selection (channel-backed with autosave on the context page, local
// state in the create-space flow); this component centralizes the single-
// integration constraint — the add list scopes to the active integration, and
// adding a repo adopts its integration while emptying resets it.
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
  // When there's nothing to add, keep the button visible but disabled with a
  // reason, rather than a dead-end "No repositories" control.
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
    <Flex align="center" gap="2" wrap="wrap" className="min-h-7">
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
