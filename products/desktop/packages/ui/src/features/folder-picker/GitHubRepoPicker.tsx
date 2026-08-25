import {
  ArrowClockwise,
  CaretDown,
  GithubLogo,
  MagnifyingGlass,
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
  Spinner,
  Text,
} from "@posthog/quill";
import { Tooltip } from "@posthog/ui/primitives/Tooltip";
import { FIELD_TRIGGER_CLASS } from "@posthog/ui/styles/fieldTrigger";
import { defaultFilter } from "cmdk";
import { type RefObject, useEffect, useMemo, useRef, useState } from "react";

const COMBOBOX_INITIAL_LIMIT = 50;
const LOAD_MORE_INDICATOR_DELAY_MS = 200;

function useDelayedVisibility(visible: boolean, delay: number): boolean {
  const [delayedVisible, setDelayedVisible] = useState(false);

  useEffect(() => {
    if (!visible) {
      setDelayedVisible(false);
      return;
    }

    const timeout = window.setTimeout(() => setDelayedVisible(true), delay);
    return () => window.clearTimeout(timeout);
  }, [delay, visible]);

  return delayedVisible;
}

interface GitHubRepoPickerProps {
  value: string | null;
  onChange: (repo: string | null) => void;
  repositories: string[];
  isLoading: boolean;
  isLoadingMore?: boolean;
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
  triggerClassName?: string;
  /** "field" matches FolderPicker's select-style trigger. */
  variant?: "button" | "field";
}

export function GitHubRepoPicker({
  value,
  onChange,
  repositories,
  isLoading,
  isLoadingMore = false,
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
  triggerClassName,
  variant = "button",
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
  const effectiveIsLoadingMore = isLoadingMore;
  const showInlineLoadingState =
    remoteMode && open && isLoading && !effectiveIsLoadingMore;
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
  const showLoadingMore = useDelayedVisibility(
    effectiveIsLoadingMore,
    LOAD_MORE_INDICATOR_DELAY_MS,
  );

  useEffect(() => {
    if (onlyRepo && value !== onlyRepo) {
      onChange(onlyRepo);
    }
  }, [onlyRepo, value, onChange]);

  const loadMore = () => {
    if (!hasMore || isLoading || effectiveIsLoadingMore) return;

    if (remoteMode) {
      onLoadMore?.();
      return;
    }

    setVisibleLimit((currentLimit) => currentLimit + COMBOBOX_INITIAL_LIMIT);
  };

  if (isLoading && !effectiveIsLoadingMore && !showInlineLoadingState) {
    return (
      <Button
        variant="outline"
        disabled
        size={buttonSize}
        className={`${buttonTextClass} ${triggerClassName ?? ""}`}
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
        className={`${buttonTextClass} ${triggerClassName ?? ""}`}
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
            className={`pointer-events-none min-w-0 max-w-full cursor-default justify-start disabled:opacity-100 ${buttonTextClass} ${triggerClassName ?? ""}`}
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
      filter={remoteMode ? null : undefined}
      limit={remoteMode ? undefined : visibleLimit}
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
          variant === "field" ? (
            <button
              ref={triggerRef}
              type="button"
              disabled={disabled}
              aria-label="Repository"
              className={`${FIELD_TRIGGER_CLASS} ${triggerClassName ?? ""}`}
            >
              <div className="flex min-w-0 flex-1 items-center gap-2">
                <GithubLogo size={16} className="shrink-0 text-(--gray-12)" />
                <span
                  className="min-w-0 max-w-full truncate text-left font-medium text-(--gray-12)"
                  title={value ?? undefined}
                >
                  {value ?? placeholder}
                </span>
              </div>
              <CaretDown size={14} className="shrink-0 text-(--gray-9)" />
            </button>
          ) : (
            <Button
              ref={triggerRef}
              variant="outline"
              size={buttonSize}
              disabled={disabled}
              aria-label="Repository"
              className={`${buttonTextClass} ${triggerClassName ?? ""}`}
            >
              <GithubLogo size={14} weight="regular" className="shrink-0" />
              <span className="min-w-0 truncate">{value ?? placeholder}</span>
            </Button>
          )
        }
      />
      <ComboboxContent
        anchor={anchor ?? triggerRef}
        side="bottom"
        sideOffset={6}
        className="flex h-80 w-80 flex-col"
      >
        {showSearchInput ? (
          <ComboboxInput
            placeholder="Search repositories..."
            showTrigger={false}
          >
            <InputGroupAddon align="inline-start">
              <MagnifyingGlass size={14} />
            </InputGroupAddon>
            {onRefresh ? (
              <InputGroupAddon align="inline-end">
                <InputGroupButton
                  size="icon-xs"
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
                </InputGroupButton>
              </InputGroupAddon>
            ) : null}
          </ComboboxInput>
        ) : null}
        <ComboboxEmpty
          className={
            showInlineLoadingState
              ? "flex-1 flex-col items-center justify-center gap-2"
              : undefined
          }
        >
          {showInlineLoadingState ? (
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
              disabled={effectiveIsLoadingMore}
              loading={showLoadingMore}
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
