import { GithubLogo } from "@phosphor-icons/react";
import {
  Button,
  Combobox,
  ComboboxChip,
  ComboboxChips,
  ComboboxChipsInput,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxItem,
  ComboboxList,
  ComboboxValue,
  Spinner,
  Text,
} from "@posthog/quill";
import { useRef } from "react";

interface GitHubRepoMultiPickerProps {
  value: string[];
  onChange: (repos: string[]) => void;
  /** Repositories to offer; selected repos not in this list stay selectable as chips. */
  repositories: string[];
  isLoading: boolean;
  isLoadingMore?: boolean;
  hasMore?: boolean;
  onLoadMore?: () => void;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  searchQuery?: string;
  onSearchQueryChange?: (value: string) => void;
  placeholder?: string;
  disabled?: boolean;
}

/**
 * Multi-select sibling of `GitHubRepoPicker`. Kept separate because the single-select picker's
 * `value: string | null` contract has several callers that would all need touching otherwise.
 */
export function GitHubRepoMultiPicker({
  value,
  onChange,
  repositories,
  isLoading,
  isLoadingMore = false,
  hasMore = false,
  onLoadMore,
  open,
  onOpenChange,
  searchQuery,
  onSearchQueryChange,
  placeholder = "Search repositories…",
  disabled = false,
}: GitHubRepoMultiPickerProps) {
  const anchorRef = useRef<HTMLDivElement>(null);
  const items = Array.from(new Set([...value, ...repositories]));

  return (
    <Combobox<string, true>
      multiple
      items={items}
      filter={null}
      value={value}
      onValueChange={(next) => onChange(next ?? [])}
      open={open}
      onOpenChange={onOpenChange}
      inputValue={searchQuery}
      onInputValueChange={(next) => onSearchQueryChange?.(next)}
      disabled={disabled}
    >
      <ComboboxChips
        ref={anchorRef}
        className="flex min-h-9 w-full flex-wrap items-center gap-1 rounded-(--radius-2) border border-border bg-(--color-panel-solid) px-1.5 py-1"
      >
        <span className="shrink-0 pl-1 text-(--gray-11)">
          <GithubLogo size={14} weight="regular" />
        </span>
        <ComboboxValue>
          {(selected: string[]) =>
            selected.map((repo) => (
              <ComboboxChip key={repo} title={repo} showRemove>
                {repo}
              </ComboboxChip>
            ))
          }
        </ComboboxValue>
        <ComboboxChipsInput
          placeholder={value.length === 0 ? placeholder : ""}
          aria-label="Repositories"
          className="min-w-24 flex-1 bg-transparent text-[13px] text-gray-12 outline-none placeholder:text-gray-10"
        />
      </ComboboxChips>
      <ComboboxContent
        anchor={anchorRef}
        align="start"
        sideOffset={4}
        className="flex max-h-80 w-(--anchor-width) min-w-80 flex-col"
      >
        <ComboboxEmpty
          className={
            isLoading
              ? "flex flex-1 flex-col items-center justify-center gap-2 py-4"
              : undefined
          }
        >
          {isLoading ? (
            <>
              <Spinner className="size-4" />
              <Text size="sm" variant="muted">
                Loading repositories
              </Text>
            </>
          ) : (
            "No repositories found."
          )}
        </ComboboxEmpty>
        <ComboboxList className="flex-1">
          {(repo: string) => (
            <ComboboxItem key={repo} value={repo}>
              {repo}
            </ComboboxItem>
          )}
        </ComboboxList>
        {hasMore ? (
          <div className="shrink-0 border-t p-1">
            <Button
              variant="outline"
              size="sm"
              className="w-full"
              disabled={isLoadingMore}
              loading={isLoadingMore}
              onClick={onLoadMore}
            >
              Load more repositories
            </Button>
          </div>
        ) : null}
      </ComboboxContent>
    </Combobox>
  );
}
