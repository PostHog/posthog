import { ArrowClockwise, GithubLogo } from "@phosphor-icons/react";
import {
  Button,
  Combobox,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxItem,
  ComboboxList,
  ComboboxListFooter,
  ComboboxTrigger,
} from "@posthog/quill";
import { Tooltip } from "@posthog/ui/primitives/Tooltip";
import { defaultFilter } from "cmdk";
import { type RefObject, useEffect, useMemo, useRef, useState } from "react";

const COMBOBOX_INITIAL_LIMIT = 50;

interface GitHubRepoPickerProps {
  value: string | null;
  onChange: (repo: string | null) => void;
  repositories: string[];
  isLoading: boolean;
  placeholder?: string;
  size?: "1" | "2";
  disabled?: boolean;
  anchor?: RefObject<HTMLElement | null>;
  /** When false, the list is shown without a filter field (e.g. short lists in modals). */
  showSearchInput?: boolean;
  onRefresh?: () => void;
  isRefreshing?: boolean;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  searchQuery?: string;
  onSearchQueryChange?: (value: string) => void;
  hasMore?: boolean;
  onLoadMore?: () => void;
}

export function GitHubRepoPicker({
  value,
  onChange,
  repositories,
  isLoading,
  placeholder = "Select repository...",
  size = "1",
  disabled = false,
  anchor,
  showSearchInput = true,
  onRefresh,
  isRefreshing = false,
  open: controlledOpen,
  onOpenChange,
  searchQuery: controlledSearchQuery,
  onSearchQueryChange,
  hasMore: controlledHasMore,
  onLoadMore,
}: GitHubRepoPickerProps) {
  const buttonSize = size === "2" ? "lg" : "sm";
  const buttonTextClass = size === "2" ? "text-[13px]" : "";
  const triggerRef = useRef<HTMLButtonElement>(null);
  const [uncontrolledOpen, setUncontrolledOpen] = useState(false);
  const [uncontrolledSearchQuery, setUncontrolledSearchQuery] = useState("");
  const [visibleLimit, setVisibleLimit] = useState(COMBOBOX_INITIAL_LIMIT);
  const open = controlledOpen ?? uncontrolledOpen;
  const searchQuery = controlledSearchQuery ?? uncontrolledSearchQuery;
  const remoteMode =
    controlledSearchQuery !== undefined ||
    onSearchQueryChange !== undefined ||
    controlledHasMore !== undefined ||
    onLoadMore !== undefined;
  const showInlineLoadingState = remoteMode && open && isLoading;
  const onlyRepo =
    !remoteMode && repositories.length === 1 ? repositories[0] : null;
  const trimmedSearchQuery = searchQuery.trim();
  const filteredRepositoryCount = useMemo(() => {
    if (!trimmedSearchQuery) {
      return repositories.length;
    }

    return repositories.reduce(
      (count, repo) =>
        count + (defaultFilter(repo, trimmedSearchQuery) > 0 ? 1 : 0),
      0,
    );
  }, [repositories, trimmedSearchQuery]);
  const hasMore = controlledHasMore ?? filteredRepositoryCount > visibleLimit;

  useEffect(() => {
    if (onlyRepo && value !== onlyRepo) {
      onChange(onlyRepo);
    }
  }, [onlyRepo, value, onChange]);

  if (isLoading && !showInlineLoadingState) {
    return (
      <Button
        variant="outline"
        disabled
        size={buttonSize}
        className={buttonTextClass}
      >
        <GithubLogo size={16} weight="regular" className="shrink-0" />
        Loading repos...
      </Button>
    );
  }

  const hasActiveRemoteSearch =
    remoteMode && (open || trimmedSearchQuery.length > 0);

  if (
    repositories.length === 0 &&
    !showInlineLoadingState &&
    !hasActiveRemoteSearch
  ) {
    return (
      <Button
        variant="outline"
        disabled
        size={buttonSize}
        className={buttonTextClass}
      >
        <GithubLogo size={16} weight="regular" className="shrink-0" />
        No GitHub repos
      </Button>
    );
  }

  if (onlyRepo) {
    return (
      <Tooltip content="Only one GitHub repository is connected, so there's nothing to pick.">
        <span className="inline-flex min-w-0 max-w-full">
          <Button
            type="button"
            variant="outline"
            size={buttonSize}
            disabled
            aria-label="Repository"
            className={`pointer-events-none min-w-0 max-w-full cursor-default justify-start disabled:opacity-100 ${buttonTextClass}`}
          >
            <GithubLogo size={14} weight="regular" className="shrink-0" />
            <span className="min-w-0 truncate">{onlyRepo}</span>
          </Button>
        </span>
      </Tooltip>
    );
  }

  return (
    <Combobox
      items={repositories}
      limit={visibleLimit}
      value={value}
      onValueChange={(v) => {
        onChange(v ? (v as string) : null);
      }}
      open={open}
      onOpenChange={(nextOpen) => {
        setUncontrolledOpen(nextOpen);
        onOpenChange?.(nextOpen);
        if (!nextOpen) {
          setUncontrolledSearchQuery("");
          onSearchQueryChange?.("");
          setVisibleLimit(COMBOBOX_INITIAL_LIMIT);
        }
      }}
      inputValue={searchQuery}
      onInputValueChange={(nextSearchQuery) => {
        setUncontrolledSearchQuery(nextSearchQuery);
        onSearchQueryChange?.(nextSearchQuery);
        setVisibleLimit(COMBOBOX_INITIAL_LIMIT);
      }}
      disabled={disabled}
    >
      <ComboboxTrigger
        render={
          <Button
            ref={triggerRef}
            variant="outline"
            size={buttonSize}
            disabled={disabled}
            aria-label="Repository"
            className={buttonTextClass}
          >
            <GithubLogo size={14} weight="regular" className="shrink-0" />
            <span className="min-w-0 truncate">{value ?? placeholder}</span>
          </Button>
        }
      />
      <ComboboxContent
        anchor={anchor ?? triggerRef}
        side="bottom"
        sideOffset={6}
        className="min-w-[280px]"
      >
        {showSearchInput ? (
          <div className="flex min-w-0 items-center gap-1 pe-2">
            <div className="min-w-0 flex-1">
              <ComboboxInput placeholder="Search repositories..." />
            </div>
            {onRefresh ? (
              <Button
                variant="outline"
                size="sm"
                disabled={disabled || isRefreshing}
                aria-label="Refresh repositories"
                onMouseDown={(event) => {
                  event.preventDefault();
                  event.stopPropagation();
                }}
                onClick={(event) => {
                  event.preventDefault();
                  event.stopPropagation();
                  onRefresh();
                }}
              >
                <ArrowClockwise
                  size={14}
                  className={isRefreshing ? "animate-spin" : undefined}
                />
              </Button>
            ) : null}
          </div>
        ) : null}
        <ComboboxEmpty>
          {showInlineLoadingState
            ? "Loading repositories..."
            : "No repositories found."}
        </ComboboxEmpty>
        <ComboboxList>
          {(repo: string) => (
            <ComboboxItem key={repo} value={repo}>
              {repo}
            </ComboboxItem>
          )}
        </ComboboxList>

        {(hasMore ||
          (remoteMode
            ? repositories.length > COMBOBOX_INITIAL_LIMIT
            : filteredRepositoryCount > COMBOBOX_INITIAL_LIMIT)) && (
          <ComboboxListFooter>
            <div className="px-2 pb-2">
              <div className="px-1 pb-2 text-center text-muted-foreground text-xs">
                {remoteMode
                  ? trimmedSearchQuery
                    ? `Showing ${repositories.length}${hasMore ? "+" : ""} matches`
                    : `Showing ${repositories.length}${hasMore ? "+" : ""} repositories`
                  : trimmedSearchQuery
                    ? `Showing ${Math.min(visibleLimit, filteredRepositoryCount)} of ${filteredRepositoryCount} matches`
                    : `Showing ${Math.min(visibleLimit, repositories.length)} of ${repositories.length}`}
              </div>
              {hasMore ? (
                <Button
                  variant="outline"
                  size="sm"
                  className="w-full justify-center"
                  onMouseDown={(event) => {
                    event.preventDefault();
                    event.stopPropagation();
                  }}
                  onClick={(event) => {
                    event.preventDefault();
                    event.stopPropagation();
                    if (remoteMode) {
                      onLoadMore?.();
                      return;
                    }

                    setVisibleLimit(
                      (currentLimit) => currentLimit + COMBOBOX_INITIAL_LIMIT,
                    );
                  }}
                >
                  Load more
                </Button>
              ) : null}
            </div>
          </ComboboxListFooter>
        )}
      </ComboboxContent>
    </Combobox>
  );
}
