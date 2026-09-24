import {
  CaretDownIcon,
  FolderOpenIcon,
  GearSixIcon,
  GithubLogoIcon,
  MagnifyingGlassIcon,
} from "@phosphor-icons/react";
import {
  Button,
  Combobox,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxItem,
  ComboboxList,
  ComboboxTrigger,
  InputGroupAddon,
  InputGroupButton,
  Text,
} from "@posthog/quill";
import { MAX_REPOSITORIES } from "@posthog/ui/features/integrations/components/RepositoriesField";
import { useGithubRepositories } from "@posthog/ui/features/integrations/useIntegrations";
import { Spinner } from "@posthog/ui/primitives/Spinner";
import { useRef, useState } from "react";

export function taskRepositoryLabel(repositories: string[]): string {
  if (repositories.length === 0) return "Add repositories…";
  if (repositories.length === 1) return repositories[0];
  return `${repositories.length} repositories`;
}

/**
 * Resolves a combobox value change into the task's next repositories and
 * integration. Returns null when the change must be ignored: the new
 * repository has no known integration, or the list is already full.
 */
export function resolveTaskRepositorySelection({
  current,
  next,
  integrationId,
  getIntegrationIdForRepo,
  max = MAX_REPOSITORIES,
}: {
  current: string[];
  next: string[];
  integrationId: number | null;
  getIntegrationIdForRepo: (repository: string) => number | null | undefined;
  max?: number;
}): { repositories: string[]; integrationId: number | null } | null {
  if (next.length === 0) return { repositories: [], integrationId: null };
  const added = next.find((repository) => !current.includes(repository));
  if (!added) return { repositories: next, integrationId };
  if (next.length > max) return null;
  const addedIntegrationId = getIntegrationIdForRepo(added);
  if (addedIntegrationId == null) return null;
  return { repositories: next, integrationId: addedIntegrationId };
}

// Pins only what was selected at open, so a pick does not move the row under the pointer.
export function orderTaskRepositoryItems({
  pinned,
  selected,
  fetched,
  query,
}: {
  pinned: string[];
  selected: string[];
  fetched: string[];
  query: string;
}): string[] {
  const needle = query.trim().toLowerCase();
  const matches = (repository: string) =>
    repository.toLowerCase().includes(needle);
  const leading = pinned.filter(matches);
  const results = fetched.filter((repository) => !pinned.includes(repository));
  // Selected repositories stay listed (and checked) even when the remote
  // search page doesn't include them.
  const unlisted = selected.filter(
    (repository) =>
      matches(repository) &&
      !pinned.includes(repository) &&
      !fetched.includes(repository),
  );
  return [...leading, ...results, ...unlisted];
}

interface TaskRepositoryChipProps {
  cloud: boolean;
  repositories: string[];
  integrationId: number | null;
  hasFolder: boolean;
  disabled: boolean;
  onRepositoriesChange: (
    repositories: string[],
    integrationId: number | null,
  ) => void;
  /** Opens the TaskRepositoryDialog. */
  onOpenSettings: () => void;
}

/**
 * The task's repository (cloud) or folder (local) selection for the
 * composer's selector row, drawn like the WorkspaceModeSelect beside it.
 * Cloud opens an inline multi-select menu; local opens the
 * TaskRepositoryDialog.
 */
export function TaskRepositoryChip({
  cloud,
  repositories,
  integrationId,
  hasFolder,
  disabled,
  onRepositoriesChange,
  onOpenSettings,
}: TaskRepositoryChipProps) {
  if (!cloud) {
    return (
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={disabled}
        aria-label="Task folder"
        onClick={onOpenSettings}
      >
        <span className="text-muted-foreground">
          <FolderOpenIcon size={14} />
        </span>
        {hasFolder ? "Folder selected" : "Select folder…"}
      </Button>
    );
  }

  return (
    <TaskRepositoryCombobox
      repositories={repositories}
      integrationId={integrationId}
      disabled={disabled}
      onChange={onRepositoriesChange}
      onOpenSettings={onOpenSettings}
    />
  );
}

function TaskRepositoryCombobox({
  repositories,
  integrationId,
  disabled,
  onChange,
  onOpenSettings,
}: {
  repositories: string[];
  integrationId: number | null;
  disabled: boolean;
  onChange: (repositories: string[], integrationId: number | null) => void;
  onOpenSettings: () => void;
}) {
  const triggerRef = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [pinned, setPinned] = useState<string[]>(repositories);
  const {
    repositories: fetched,
    getIntegrationIdForRepo,
    isPending,
    isFetchingMore,
    hasMore,
    loadMore,
  } = useGithubRepositories(query, open, integrationId);

  const items = orderTaskRepositoryItems({
    pinned,
    selected: repositories,
    fetched,
    query,
  });
  const atLimit = repositories.length >= MAX_REPOSITORIES;
  const label = taskRepositoryLabel(repositories);

  const handleOpenChange = (next: boolean) => {
    setOpen(next);
    if (next) setPinned(repositories);
    else setQuery("");
  };

  return (
    <Combobox
      multiple
      items={items}
      filter={null}
      value={repositories}
      onValueChange={(next: string[]) => {
        const selection = resolveTaskRepositorySelection({
          current: repositories,
          next,
          integrationId,
          getIntegrationIdForRepo,
        });
        if (selection)
          onChange(selection.repositories, selection.integrationId);
      }}
      open={open}
      onOpenChange={handleOpenChange}
      inputValue={query}
      onInputValueChange={setQuery}
      disabled={disabled}
    >
      <ComboboxTrigger
        render={
          <Button
            ref={triggerRef}
            type="button"
            variant="outline"
            size="sm"
            disabled={disabled}
            aria-label="Task repositories"
            title={repositories.length > 1 ? repositories.join(", ") : label}
          >
            <span className="text-muted-foreground">
              <GithubLogoIcon size={14} />
            </span>
            <span className="min-w-0 max-w-[200px] truncate">{label}</span>
            <CaretDownIcon
              size={10}
              weight="bold"
              className="text-muted-foreground"
            />
          </Button>
        }
      />
      <ComboboxContent
        anchor={triggerRef}
        side="bottom"
        sideOffset={6}
        className="flex h-80 w-80 flex-col"
      >
        <ComboboxInput placeholder="Search repositories…" showTrigger={false}>
          <InputGroupAddon align="inline-start">
            <MagnifyingGlassIcon size={14} />
          </InputGroupAddon>
          <InputGroupAddon align="inline-end">
            <InputGroupButton
              size="icon-xs"
              aria-label="Repository settings"
              title="Repository settings"
              onClick={(event) => {
                event.preventDefault();
                event.stopPropagation();
                handleOpenChange(false);
                onOpenSettings();
              }}
            >
              <GearSixIcon size={14} />
            </InputGroupButton>
          </InputGroupAddon>
        </ComboboxInput>
        <ComboboxEmpty
          className={
            isPending
              ? "flex-1 flex-col items-center justify-center gap-2"
              : undefined
          }
        >
          {isPending ? (
            <>
              <Spinner size="md" />
              <Text size="sm" variant="muted">
                Loading repositories
              </Text>
            </>
          ) : (
            "No repositories found."
          )}
        </ComboboxEmpty>
        <ComboboxList className="flex-1">
          {(repository: string) => (
            <ComboboxItem
              key={repository}
              value={repository}
              disabled={atLimit && !repositories.includes(repository)}
            >
              {repository}
            </ComboboxItem>
          )}
        </ComboboxList>
        {hasMore ? (
          <div className="shrink-0 border-t p-1">
            <Button
              variant="outline"
              size="sm"
              className="w-full"
              disabled={isFetchingMore}
              loading={isFetchingMore}
              onClick={loadMore}
            >
              Load more repositories
            </Button>
          </div>
        ) : null}
      </ComboboxContent>
    </Combobox>
  );
}
