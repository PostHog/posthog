import {
  ArrowClockwise,
  CaretDown,
  Check,
  GitBranch,
  Plus,
  Spinner,
} from "@phosphor-icons/react";
import { useService } from "@posthog/di/react";
import { useHostTRPC } from "@posthog/host-router/react";
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
  InputGroupAddon,
  InputGroupButton,
} from "@posthog/quill";
import { getFileName } from "@posthog/shared";
import type {
  GitBusyOperation,
  GitBusyState,
} from "@posthog/shared/domain-types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type RefObject, useEffect, useMemo, useRef, useState } from "react";
import { Tooltip } from "../../../primitives/Tooltip";
import { toast } from "../../../primitives/toast";
import { invalidateGitBranchQueries } from "../gitCacheKeys";
import {
  GIT_CACHE_KEY_PROVIDER,
  type GitCacheKeyProvider,
} from "../gitCacheProvider";
import { useGitInteractionStore } from "../state/gitInteractionStore";
import { getSuggestedBranchName } from "../utils/getSuggestedBranchName";

const COMBOBOX_LIMIT = 50;

// Shared so the two "still loading branches" render sites (the empty-list
// spinner and the seeded-default row) can never drift out of sync on a copy edit.
const LOADING_BRANCHES_LABEL = "Loading branches…";

// Sentinel value for the "Create new branch" action. Rendered as a real
// ComboboxItem in the list footer so it's reachable by keyboard, not a
// plain button the combobox's roving focus skips over.
const CREATE_BRANCH_ACTION = "__create_branch__";

// Sentinel for the "Use '<input>' as branch name" action in cloud mode.
// Positioned first when the list is empty so it's auto-highlighted while the
// (slow) remote search is still running; pushed into the footer once branches
// have loaded so auto-highlight lands on a real branch (typed names that match
// a server-returned prefix would otherwise be shadowed by the literal input).
const USE_INPUT_BRANCH_ACTION = "__use_input_branch__";

function LoadingRow({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-1 px-2 py-1.5 text-muted-foreground text-xs">
      <Spinner size={12} className="animate-spin" />
      {label}
    </div>
  );
}

interface BranchSelectorProps {
  repoPath: string | null;
  currentBranch: string | null;
  defaultBranch?: string | null;
  disabled?: boolean;
  loading?: boolean;
  variant?: "outline" | "ghost";
  workspaceMode?: "worktree" | "local" | "cloud";
  selectedBranch?: string | null;
  onBranchSelect?: (branch: string | null) => void;
  cloudBranches?: string[];
  cloudBranchesHasMore?: boolean;
  cloudBranchesLoading?: boolean;
  cloudBranchesFetchingMore?: boolean;
  cloudSearchQuery?: string;
  onCloudPickerOpen?: () => void;
  onCloudPickerClose?: () => void;
  onCloudSearchChange?: (value: string) => void;
  onCloudLoadMore?: () => void;
  onCloudBranchCommit?: () => void;
  onRefresh?: () => void;
  isRefreshing?: boolean;
  taskId?: string;
  anchor?: RefObject<HTMLElement | null>;
  /**
   * Local-repo busy state (rebase, merge, cherry-pick, revert in progress).
   * Used to show a clearer label and prevent checkout attempts that would
   * fail while the working tree is mid-operation. Only applies in local mode.
   */
  busyState?: GitBusyState;
}

const BUSY_OPERATION_LABEL: Record<GitBusyOperation, string> = {
  rebase: "Rebasing",
  merge: "Merging",
  "cherry-pick": "Cherry-picking",
  revert: "Reverting",
};

export function BranchSelector({
  repoPath,
  currentBranch,
  defaultBranch,
  disabled,
  loading,
  workspaceMode,
  selectedBranch,
  onBranchSelect,
  cloudBranches,
  cloudBranchesHasMore,
  cloudBranchesLoading,
  cloudBranchesFetchingMore,
  cloudSearchQuery,
  onCloudPickerOpen,
  onCloudPickerClose,
  onCloudSearchChange,
  onCloudLoadMore,
  onCloudBranchCommit,
  onRefresh,
  isRefreshing = false,
  taskId,
  anchor,
  busyState,
}: BranchSelectorProps) {
  const [open, setOpen] = useState(false);
  const [hovered, setHovered] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const localAnchorRef = useRef<HTMLButtonElement>(null);
  const trpc = useHostTRPC();
  const queryClient = useQueryClient();
  const cacheKeyProvider = useService<GitCacheKeyProvider>(
    GIT_CACHE_KEY_PROVIDER,
  );
  const { actions } = useGitInteractionStore();

  const isCloudMode = workspaceMode === "cloud";
  const isSelectionOnly = workspaceMode === "worktree" || isCloudMode;

  // The branch we auto-selected, so we can tell our own pick apart from one the
  // user made. Lets us correct a stale default (e.g. a cached "trunk" that the
  // live list later contradicts) without ever clobbering a deliberate choice.
  const autoSelectedBranchRef = useRef<string | null>(null);
  useEffect(() => {
    if (!isSelectionOnly || !defaultBranch || !onBranchSelect) return;
    // Adopt the default when nothing is selected yet, or when the default has
    // changed out from under a value we ourselves auto-selected — but leave a
    // user's own selection alone.
    const selectionIsOurs =
      !selectedBranch || selectedBranch === autoSelectedBranchRef.current;
    if (selectionIsOurs && selectedBranch !== defaultBranch) {
      autoSelectedBranchRef.current = defaultBranch;
      onBranchSelect(defaultBranch);
    }
  }, [isSelectionOnly, defaultBranch, selectedBranch, onBranchSelect]);

  const { data: localBranches = [], isLoading: localBranchesLoading } =
    useQuery({
      ...trpc.git.getAllBranches.queryOptions({
        directoryPath: repoPath as string,
      }),
      enabled: !isCloudMode && !!repoPath,
      staleTime: 60_000,
    });

  // Branches already checked out in another checkout of this repo (main clone
  // or worktree). Git refuses to check those out here, and for worktree mode
  // it tells the user where a branch already lives.
  const { data: repoCheckouts = [] } = useQuery({
    ...trpc.workspace.listRepoCheckouts.queryOptions({
      repoPath: repoPath as string,
    }),
    enabled: open && !isCloudMode && !!repoPath,
    staleTime: 60_000,
  });
  const checkedOutElsewhere = useMemo(() => {
    const byBranch = new Map<string, string>();
    for (const checkout of repoCheckouts) {
      if (checkout.branch) {
        byBranch.set(checkout.branch, getFileName(checkout.path));
      }
    }
    return byBranch;
  }, [repoCheckouts]);

  const liveBranches = isCloudMode ? (cloudBranches ?? []) : localBranches;
  const effectiveLoading = loading || (isCloudMode && cloudBranchesLoading);
  const branchListLoading = isCloudMode
    ? !!cloudBranchesLoading
    : localBranchesLoading;

  // On a cold start the live cloud branch list is still empty while the (slow)
  // remote fetch runs. Surface the known default ("trunk") branch as a real
  // list item straight away — with a loading row rendered below it — so the
  // common "start on trunk" case is pickable with zero wait. Only when there's
  // no active search: once the user types, the results should be purely what
  // the remote returns.
  const seededDefaultBranch =
    isCloudMode &&
    branchListLoading &&
    liveBranches.length === 0 &&
    !!defaultBranch &&
    !(cloudSearchQuery ?? "").trim()
      ? defaultBranch
      : null;
  const branches = seededDefaultBranch ? [seededDefaultBranch] : liveBranches;

  const checkoutMutation = useMutation({
    ...trpc.git.checkoutBranch.mutationOptions(),
    onSuccess: () => {
      if (repoPath) invalidateGitBranchQueries(repoPath);
    },
    onError: (error, { branchName }) => {
      const message =
        error instanceof Error ? error.message : "Unknown error occurred";
      if (/would be overwritten by checkout/i.test(message)) {
        toast.error(`Can't switch to ${branchName}`, {
          description:
            "You have uncommitted changes that would be overwritten. Commit or stash them first.",
        });
        return;
      }
      toast.error(`Failed to checkout ${branchName}`, {
        description: message,
      });
    },
  });

  const checkedOutBranch =
    checkoutMutation.data &&
    checkoutMutation.variables.directoryPath === repoPath &&
    currentBranch === checkoutMutation.data.previousBranch
      ? checkoutMutation.data.currentBranch
      : currentBranch;
  const displayedBranch = isSelectionOnly ? selectedBranch : checkedOutBranch;

  // In local mode, surface in-progress git operations (rebase/merge/etc.) so the
  // user understands why there's no current branch and why we won't let them
  // checkout a different one — checkout would fail with a hard-to-read git error.
  const localBusy = !isSelectionOnly && busyState?.busy === true;
  const busyOperationLabel =
    localBusy && busyState?.busy
      ? BUSY_OPERATION_LABEL[busyState.operation]
      : null;

  const displayText = effectiveLoading
    ? "Loading..."
    : busyOperationLabel && !displayedBranch
      ? busyOperationLabel
      : (displayedBranch ?? "No branch");

  // Which checkout the branch applies to. With several checkouts of the same
  // repo registered (main clone + worktrees), a bare branch name is ambiguous
  // — in local mode picking one runs a real checkout in this directory.
  const checkoutName = !isCloudMode && repoPath ? getFileName(repoPath) : null;

  const showSpinner =
    effectiveLoading || (isCloudMode && open && cloudBranchesFetchingMore);

  const isDisabled = !!(disabled || !repoPath || localBusy);
  const disabledReason =
    localBusy && busyOperationLabel
      ? `${busyOperationLabel} in progress — finish or abort it to switch branches.`
      : null;
  const inputValue = isCloudMode ? (cloudSearchQuery ?? "") : searchQuery;
  const trimmedInputValue = inputValue.trim();
  const canUseInputBranch =
    !isDisabled &&
    trimmedInputValue.length > 0 &&
    trimmedInputValue !== displayedBranch;
  const showUseInputBranchAction =
    isCloudMode &&
    canUseInputBranch &&
    !branches.some((branch) => branch === trimmedInputValue);

  const handleBranchChange = (value: string | null) => {
    if (!value) return;
    if (value === CREATE_BRANCH_ACTION) {
      setOpen(false);
      actions.openBranch(
        taskId
          ? getSuggestedBranchName(
              queryClient,
              cacheKeyProvider,
              taskId,
              repoPath ?? undefined,
            )
          : undefined,
      );
      return;
    }
    const branchName =
      value === USE_INPUT_BRANCH_ACTION ? trimmedInputValue : value;
    if (!branchName) return;
    if (isSelectionOnly) {
      onBranchSelect?.(branchName);
    } else if (branchName !== currentBranch) {
      checkoutMutation.mutate({
        directoryPath: repoPath as string,
        branchName,
      });
    }
    if (isCloudMode) {
      onCloudBranchCommit?.();
    }
    setOpen(false);
  };

  const handleOpenChange = (next: boolean) => {
    setOpen(next);
    if (isCloudMode && next) {
      onCloudPickerOpen?.();
    } else if (isCloudMode && !next) {
      onCloudPickerClose?.();
    }
  };

  const handleUseInputBranch = () => {
    if (!canUseInputBranch) return;
    handleBranchChange(trimmedInputValue);
  };

  const useInputBranchPosition: "leading" | "trailing" | null =
    showUseInputBranchAction
      ? branches.length === 0
        ? "leading"
        : "trailing"
      : null;
  const comboboxItems = isCloudMode
    ? useInputBranchPosition === "leading"
      ? [USE_INPUT_BRANCH_ACTION, ...branches]
      : useInputBranchPosition === "trailing"
        ? [...branches, USE_INPUT_BRANCH_ACTION]
        : branches
    : [...branches, CREATE_BRANCH_ACTION];

  return (
    <Combobox
      items={comboboxItems}
      limit={COMBOBOX_LIMIT}
      autoHighlight
      value={displayedBranch}
      inputValue={inputValue}
      onInputValueChange={
        isCloudMode
          ? (value) => onCloudSearchChange?.((value as string | null) ?? "")
          : setSearchQuery
      }
      onValueChange={(v) => handleBranchChange(v as string | null)}
      open={open}
      onOpenChange={handleOpenChange}
      disabled={isDisabled}
      filter={isCloudMode ? null : undefined}
    >
      <Tooltip
        content={
          disabledReason ??
          (checkoutName && repoPath ? (
            <span className="flex flex-col">
              <span>{displayedBranch ?? "Switch branch"}</span>
              <span className="text-gray-10">in {repoPath}</span>
            </span>
          ) : (
            (displayedBranch ?? "Switch branch")
          ))
        }
        side="bottom"
        open={hovered && !open && !effectiveLoading}
      >
        <ComboboxTrigger
          render={
            <Button
              ref={localAnchorRef}
              variant="outline"
              size="sm"
              disabled={isDisabled}
              aria-label="Branch"
              onMouseEnter={() => setHovered(true)}
              onMouseLeave={() => setHovered(false)}
              className="min-w-0 max-w-[250px] shrink"
            >
              {showSpinner ? (
                <Spinner size={14} className="shrink-0 animate-spin" />
              ) : (
                <GitBranch size={14} weight="regular" className="shrink-0" />
              )}
              <span className="min-w-0 truncate">{displayText}</span>
              <CaretDown
                size={10}
                weight="bold"
                className="text-muted-foreground"
              />
            </Button>
          }
        />
      </Tooltip>
      <ComboboxContent
        anchor={anchor ?? localAnchorRef}
        side="bottom"
        sideOffset={6}
        className="min-w-[240px]"
      >
        {/*
          ComboboxInput must be a direct child of ComboboxContent so quill's
          `.quill-combobox__content > [data-slot=combobox-input-group-wrapper]`
          rule applies the p-1 padding + border-bottom. The action buttons are
          passed as children — they render inside the input's own InputGroup.
        */}
        <ComboboxInput
          placeholder="Search branches..."
          showTrigger={false}
          onKeyDownCapture={(event) => {
            if (
              event.key !== "Enter" ||
              event.nativeEvent.isComposing ||
              !canUseInputBranch
            ) {
              return;
            }

            // If the combobox already has a highlighted item, let Base UI select it.
            if (event.currentTarget.getAttribute("aria-activedescendant")) {
              return;
            }

            event.preventDefault();
            event.stopPropagation();
            handleUseInputBranch();
          }}
        >
          <InputGroupAddon align="inline-end">
            <Tooltip content="Use this branch name" side="bottom">
              <InputGroupButton
                variant="outline"
                size="icon-xs"
                disabled={!canUseInputBranch}
                aria-label="Use this branch name"
                onMouseDown={(event) => {
                  // Keep focus inside the combobox so the popover doesn't close before click.
                  event.preventDefault();
                  event.stopPropagation();
                }}
                onClick={(event) => {
                  event.preventDefault();
                  event.stopPropagation();
                  handleUseInputBranch();
                }}
              >
                <Check size={14} />
              </InputGroupButton>
            </Tooltip>
            {onRefresh ? (
              <InputGroupButton
                size="icon-xs"
                disabled={isDisabled || isRefreshing}
                aria-label="Refresh branches"
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
            ) : null}
          </InputGroupAddon>
        </ComboboxInput>

        {checkoutName ? (
          <div
            className="truncate border-border border-b px-2 py-1.5 text-muted-foreground text-xs"
            title={repoPath ?? undefined}
          >
            {isSelectionOnly ? "Base branch for " : "Branch in "}
            <span className="font-medium">{checkoutName}</span>
          </div>
        ) : null}

        {isCloudMode && cloudBranchesFetchingMore ? (
          <LoadingRow label={`Loading more (${branches.length})…`} />
        ) : null}

        {branchListLoading && branches.length === 0 ? (
          <LoadingRow label={LOADING_BRANCHES_LABEL} />
        ) : (
          <ComboboxEmpty>No branches found.</ComboboxEmpty>
        )}

        <ComboboxList className="max-h-[min(14rem,calc(var(--available-height,14rem)-5rem))]">
          {(item: string) => {
            if (item === CREATE_BRANCH_ACTION) {
              return (
                <ComboboxListFooter key="footer">
                  <ComboboxItem
                    value={CREATE_BRANCH_ACTION}
                    title="Create new branch"
                    className="text-accent-foreground"
                  >
                    <Plus size={11} weight="bold" />
                    Create new branch
                  </ComboboxItem>
                </ComboboxListFooter>
              );
            }
            if (item === USE_INPUT_BRANCH_ACTION) {
              const useInputItem = (
                <ComboboxItem
                  key={USE_INPUT_BRANCH_ACTION}
                  value={USE_INPUT_BRANCH_ACTION}
                  title={`Use "${trimmedInputValue}" as branch name`}
                  className="text-accent-foreground"
                >
                  <Plus size={11} weight="bold" />
                  Use "{trimmedInputValue}" as branch name
                </ComboboxItem>
              );
              if (useInputBranchPosition === "trailing") {
                return (
                  <ComboboxListFooter key="use-input-footer">
                    {useInputItem}
                  </ComboboxListFooter>
                );
              }
              return useInputItem;
            }
            const elsewhere = checkedOutElsewhere.get(item);
            return (
              <ComboboxItem
                key={item}
                value={item}
                title={
                  elsewhere ? `${item} — checked out in ${elsewhere}` : item
                }
                className="relative"
              >
                <span className="min-w-0 flex-1 truncate">{item}</span>
                {elsewhere ? (
                  <span className="ml-auto shrink-0 text-[10px] text-muted-foreground">
                    in {elsewhere}
                  </span>
                ) : null}
              </ComboboxItem>
            );
          }}
        </ComboboxList>

        {/*
          Cold start: the default ("trunk") branch is seeded as the only list
          item while the remote list loads. A loading row directly below it
          makes clear the rest of the branches are still on the way.
        */}
        {seededDefaultBranch ? (
          <LoadingRow label={LOADING_BRANCHES_LABEL} />
        ) : null}

        {isCloudMode && cloudBranchesHasMore ? (
          <ComboboxListFooter>
            <div className="px-2 pb-2">
              <Button
                variant="outline"
                size="sm"
                className="w-full justify-center"
                disabled={cloudBranchesFetchingMore}
                onMouseDown={(event) => {
                  event.preventDefault();
                  event.stopPropagation();
                }}
                onClick={(event) => {
                  event.preventDefault();
                  event.stopPropagation();
                  onCloudLoadMore?.();
                }}
              >
                {cloudBranchesFetchingMore ? (
                  <>
                    <Spinner size={14} className="animate-spin" />
                    Loading more…
                  </>
                ) : (
                  "Load more"
                )}
              </Button>
            </div>
          </ComboboxListFooter>
        ) : null}

        {!isCloudMode && branches.length > COMBOBOX_LIMIT ? (
          <div className="px-2 py-1.5 text-center text-muted-foreground text-xs">
            {searchQuery
              ? `Showing up to ${COMBOBOX_LIMIT} matches - refine your search`
              : `Showing ${COMBOBOX_LIMIT} of ${branches.length} - type to filter`}
          </div>
        ) : null}
      </ComboboxContent>
    </Combobox>
  );
}
