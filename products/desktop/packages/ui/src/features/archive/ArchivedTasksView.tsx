import {
  CaretDown,
  CaretUp,
  Check,
  Cloud as CloudIcon,
  GitBranch as GitBranchIcon,
  Laptop as LaptopIcon,
  MagnifyingGlass,
} from "@phosphor-icons/react";
import type { RestoreOutcome } from "@posthog/core/archive/archivedTasksController";
import {
  type ArchivedTaskWithDetails,
  deriveUniqueRepos,
  filterAndSortArchivedTasks,
  formatRelativeDate,
  mergeArchivedWithTasks,
  type ArchiveSortColumn as SortColumn,
  type ArchiveSortState as SortState,
  withRepoNames,
} from "@posthog/core/archive/archiveListView";
import { useHostTRPC } from "@posthog/host-router/react";
import type { WorkspaceMode } from "@posthog/shared";
import { taskDetailQuery } from "@posthog/ui/features/tasks/queries";
import { openTask } from "@posthog/ui/router/useOpenTask";
import {
  AlertDialog,
  Box,
  Button,
  Dialog,
  Flex,
  Popover,
  Table,
  Text,
  TextField,
} from "@radix-ui/themes";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useVirtualizer } from "@tanstack/react-virtual";
import { useMemo, useRef, useState } from "react";
import { useSetHeaderContent } from "../../hooks/useSetHeaderContent";
import { DotsCircleSpinner } from "../../primitives/DotsCircleSpinner";
import { Tooltip } from "../../primitives/Tooltip";
import { toast } from "../../primitives/toast";
import { useTaskSummaries, useTasks } from "../tasks/useTasks";
import { useUnarchiveTask } from "./useUnarchiveTask";

const ICON_SIZE = 12;

function ModeIcon({ mode }: { mode: WorkspaceMode }) {
  if (mode === "cloud") {
    return (
      <Tooltip content="Cloud">
        <span className="flex items-center justify-center">
          <CloudIcon size={ICON_SIZE} className="text-gray-10" />
        </span>
      </Tooltip>
    );
  }
  if (mode === "worktree") {
    return (
      <Tooltip content="Worktree">
        <span className="flex items-center justify-center">
          <GitBranchIcon size={ICON_SIZE} className="text-gray-10" />
        </span>
      </Tooltip>
    );
  }
  return (
    <Tooltip content="Local">
      <span className="flex items-center justify-center">
        <LaptopIcon size={ICON_SIZE} className="text-gray-10" />
      </span>
    </Tooltip>
  );
}

function SortableColumnHeader({
  column,
  label,
  sort,
  onSort,
  width,
}: {
  column: SortColumn;
  label: string;
  sort: SortState;
  onSort: (column: SortColumn) => void;
  width?: string;
}) {
  const isActive = sort.column === column;
  return (
    <Table.ColumnHeaderCell
      className="font-normal text-[13px] text-gray-11"
      style={width ? { width } : undefined}
    >
      <button
        type="button"
        className="inline-flex items-center gap-0.5 text-gray-11 transition-colors hover:text-gray-12"
        onClick={() => onSort(column)}
      >
        {label}
        {isActive &&
          (sort.direction === "asc" ? (
            <CaretUp size={10} weight="fill" />
          ) : (
            <CaretDown size={10} weight="fill" />
          ))}
      </button>
    </Table.ColumnHeaderCell>
  );
}

const filterItemClassName =
  "flex w-full items-center justify-between rounded-sm px-1.5 py-1 text-left text-[13px] text-gray-12 transition-colors hover:bg-gray-3";

function RepositoryFilter({
  repos,
  selectedRepo,
  onSelect,
}: {
  repos: string[];
  selectedRepo: string | null;
  onSelect: (repo: string | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const selectRepo = (repo: string | null) => {
    onSelect(repo);
    setOpen(false);
  };

  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger>
        <button
          type="button"
          className="inline-flex h-8 items-center gap-1 rounded-md border border-gray-6 px-2 text-[13px] text-gray-11 transition-colors hover:bg-gray-3 hover:text-gray-12"
        >
          Repository: {selectedRepo ?? "All"}
          <CaretDown size={10} />
          {selectedRepo !== null && (
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-accent-9" />
          )}
        </button>
      </Popover.Trigger>
      <Popover.Content
        align="start"
        side="bottom"
        sideOffset={4}
        className="min-w-[180px] p-[6px]"
      >
        <Flex direction="column" gap="0">
          <button
            type="button"
            className={filterItemClassName}
            onClick={() => selectRepo(null)}
          >
            <span>All repositories</span>
            {selectedRepo === null && (
              <Check size={12} className="text-gray-12" />
            )}
          </button>
          {repos.map((repo) => (
            <button
              key={repo}
              type="button"
              className={filterItemClassName}
              onClick={() => selectRepo(repo)}
            >
              <span className="max-w-[200px] truncate">{repo}</span>
              {selectedRepo === repo && (
                <Check size={12} className="text-gray-12" />
              )}
            </button>
          ))}
        </Flex>
      </Popover.Content>
    </Popover.Root>
  );
}

interface BranchNotFoundPrompt {
  taskId: string;
  branchName: string;
}

export type { ArchivedTaskWithDetails };

export interface ArchivedTasksViewPresentationProps {
  items: ArchivedTaskWithDetails[];
  isLoading: boolean;
  branchNotFound: BranchNotFoundPrompt | null;
  onUnarchive: (taskId: string) => void;
  onDelete: (taskId: string) => void;
  onContextMenu: (item: ArchivedTaskWithDetails, e: React.MouseEvent) => void;
  onBranchNotFoundClose: () => void;
  onRecreateBranch: () => void;
}

export function ArchivedTasksViewPresentation({
  items,
  isLoading,
  branchNotFound,
  onUnarchive,
  onDelete,
  onContextMenu,
  onBranchNotFoundClose,
  onRecreateBranch,
}: ArchivedTasksViewPresentationProps) {
  const [searchQuery, setSearchQuery] = useState("");
  const [sort, setSort] = useState<SortState>({
    column: "archived",
    direction: "desc",
  });
  const [repoFilter, setRepoFilter] = useState<string | null>(null);
  const [deleteTargetId, setDeleteTargetId] = useState<string | null>(null);
  const tableViewportRef = useRef<HTMLDivElement>(null);

  const resetTableScroll = () => tableViewportRef.current?.scrollTo({ top: 0 });

  const handleSort = (column: SortColumn) => {
    resetTableScroll();
    setSort((prev) =>
      prev.column === column
        ? { column, direction: prev.direction === "asc" ? "desc" : "asc" }
        : { column, direction: "desc" },
    );
  };

  const itemsWithRepo = useMemo(() => withRepoNames(items), [items]);

  const uniqueRepos = useMemo(
    () => deriveUniqueRepos(itemsWithRepo),
    [itemsWithRepo],
  );

  const filteredItems = useMemo(
    () =>
      filterAndSortArchivedTasks(itemsWithRepo, {
        searchQuery,
        repoFilter,
        sort,
      }),
    [itemsWithRepo, searchQuery, repoFilter, sort],
  );
  const rowVirtualizer = useVirtualizer({
    count: filteredItems.length,
    getScrollElement: () => tableViewportRef.current,
    estimateSize: () => 37,
    overscan: 12,
  });
  const virtualRows = rowVirtualizer.getVirtualItems();
  const topSpacerHeight = virtualRows[0]?.start ?? 0;
  const bottomSpacerHeight =
    rowVirtualizer.getTotalSize() -
    (virtualRows[virtualRows.length - 1]?.end ?? 0);

  return (
    <Flex direction="column" height="100%">
      <Box px="3" pt="3" pb="2">
        <Flex gap="2" align="center">
          <TextField.Root
            size="2"
            placeholder="Filter by title or task ID..."
            value={searchQuery}
            onChange={(e) => {
              resetTableScroll();
              setSearchQuery(e.target.value);
            }}
            className="min-w-0 flex-1 text-[13px]"
          >
            <TextField.Slot>
              <MagnifyingGlass size={14} />
            </TextField.Slot>
          </TextField.Root>
          <RepositoryFilter
            repos={uniqueRepos}
            selectedRepo={repoFilter}
            onSelect={(repo) => {
              resetTableScroll();
              setRepoFilter(repo);
            }}
          />
        </Flex>
      </Box>

      <Box
        ref={tableViewportRef}
        className="flex-1 overflow-y-auto"
        style={{ scrollbarGutter: "stable" }}
      >
        {isLoading ? (
          <Flex align="center" justify="center" gap="2" py="8">
            <DotsCircleSpinner size={16} className="text-gray-10" />
            <Text className="text-[13px] text-gray-10">
              Loading archived tasks...
            </Text>
          </Flex>
        ) : filteredItems.length === 0 ? (
          <Flex align="center" justify="center" py="8">
            <Text className="text-[13px] text-gray-10">
              {items.length === 0 ? "No archived tasks" : "No matching tasks"}
            </Text>
          </Flex>
        ) : (
          <Table.Root
            size="1"
            className="[&_td]:!py-1.5 [&_th]:!py-1.5 [&_table]:w-full [&_table]:table-fixed [&_tbody_tr:hover]:bg-gray-4 [&_td]:overflow-hidden [&_td]:align-middle [&_th]:align-middle"
          >
            <Table.Header>
              <Table.Row>
                <Table.ColumnHeaderCell className="w-[40%] font-normal text-[13px] text-gray-11">
                  Title
                </Table.ColumnHeaderCell>
                <SortableColumnHeader
                  column="created"
                  label="Created"
                  sort={sort}
                  onSort={handleSort}
                  width="15%"
                />
                <SortableColumnHeader
                  column="archived"
                  label="Archived"
                  sort={sort}
                  onSort={handleSort}
                  width="15%"
                />
                <Table.ColumnHeaderCell className="w-[20%] font-normal text-[13px] text-gray-11">
                  Repository
                </Table.ColumnHeaderCell>
                <Table.ColumnHeaderCell className="w-[160px]" />
              </Table.Row>
            </Table.Header>
            <Table.Body>
              {topSpacerHeight > 0 && (
                <Table.Row aria-hidden="true">
                  <Table.Cell colSpan={5} style={{ height: topSpacerHeight }} />
                </Table.Row>
              )}
              {virtualRows.map((virtualRow) => {
                const item = filteredItems[virtualRow.index];
                return (
                  <Table.Row
                    key={item.archived.taskId}
                    onContextMenu={(e) => onContextMenu(item, e)}
                    className="group"
                  >
                    <Table.Cell>
                      <Flex align="center" gap="2">
                        <ModeIcon mode={item.archived.mode} />
                        <Text className="block truncate text-[13px]">
                          {item.task?.title ?? "Unknown task"}
                        </Text>
                      </Flex>
                    </Table.Cell>
                    <Table.Cell>
                      <Text className="block whitespace-nowrap text-[13px] text-gray-11">
                        {formatRelativeDate(item.task?.created_at)}
                      </Text>
                    </Table.Cell>
                    <Table.Cell>
                      <Text className="block whitespace-nowrap text-[13px] text-gray-11">
                        {formatRelativeDate(item.archived.archivedAt)}
                      </Text>
                    </Table.Cell>
                    <Table.Cell>
                      <Text className="block truncate text-[13px] text-gray-11">
                        {item.repoName}
                      </Text>
                    </Table.Cell>
                    <Table.Cell className="overflow-visible">
                      <Flex gap="2" className="invisible group-hover:visible">
                        <Button
                          variant="outline"
                          color="gray"
                          size="1"
                          onClick={() => onUnarchive(item.archived.taskId)}
                        >
                          Unarchive
                        </Button>
                        <Button
                          variant="outline"
                          color="red"
                          size="1"
                          onClick={() =>
                            setDeleteTargetId(item.archived.taskId)
                          }
                        >
                          Delete
                        </Button>
                      </Flex>
                    </Table.Cell>
                  </Table.Row>
                );
              })}
              {bottomSpacerHeight > 0 && (
                <Table.Row aria-hidden="true">
                  <Table.Cell
                    colSpan={5}
                    style={{ height: bottomSpacerHeight }}
                  />
                </Table.Row>
              )}
            </Table.Body>
          </Table.Root>
        )}
      </Box>

      <Dialog.Root
        open={branchNotFound !== null}
        onOpenChange={(open) => {
          if (!open) onBranchNotFoundClose();
        }}
      >
        <Dialog.Content maxWidth="420px" size="1">
          <Dialog.Title className="text-sm">
            Unarchive to new branch?
          </Dialog.Title>
          <Dialog.Description className="text-[13px]">
            <Text color="gray" className="text-[13px]">
              This workspace was last on{" "}
              <Text className="font-medium text-[13px]">
                {branchNotFound?.branchName}
              </Text>
              , but that branch has been deleted or renamed.
            </Text>
          </Dialog.Description>
          <Flex justify="end" gap="3" mt="3">
            <Dialog.Close>
              <Button variant="soft" color="gray" size="1">
                Cancel
              </Button>
            </Dialog.Close>
            <Button size="1" onClick={onRecreateBranch}>
              Unarchive to new branch
            </Button>
          </Flex>
        </Dialog.Content>
      </Dialog.Root>

      <AlertDialog.Root
        open={deleteTargetId !== null}
        onOpenChange={(open) => {
          if (!open) setDeleteTargetId(null);
        }}
      >
        <AlertDialog.Content maxWidth="420px" size="1">
          <AlertDialog.Title className="text-sm">
            Delete archived task
          </AlertDialog.Title>
          <AlertDialog.Description className="text-[13px]">
            <Text color="gray" className="text-[13px]">
              Permanently delete{" "}
              <Text className="font-medium text-[13px]">
                {items.find((i) => i.archived.taskId === deleteTargetId)?.task
                  ?.title ?? "Unknown task"}
              </Text>
              ? This cannot be undone.
            </Text>
          </AlertDialog.Description>
          <Flex justify="end" gap="3" mt="3">
            <AlertDialog.Cancel>
              <Button variant="soft" color="gray" size="1">
                Cancel
              </Button>
            </AlertDialog.Cancel>
            <AlertDialog.Action>
              <Button
                variant="solid"
                color="red"
                size="1"
                onClick={() => {
                  if (deleteTargetId) onDelete(deleteTargetId);
                  setDeleteTargetId(null);
                }}
              >
                Delete
              </Button>
            </AlertDialog.Action>
          </Flex>
        </AlertDialog.Content>
      </AlertDialog.Root>
    </Flex>
  );
}

export function ArchivedTasksView() {
  const trpc = useHostTRPC();
  const queryClient = useQueryClient();
  const { data: archivedTasks = [], isLoading: isLoadingArchived } = useQuery({
    ...trpc.archive.list.queryOptions(),
    refetchInterval: (query) =>
      query.state.data?.some((task) => task.recoveryPending) ? 1_000 : false,
  });
  const { data: listedTasks = [] } = useTasks();
  const archivedTaskIds = useMemo(
    () => archivedTasks.map((task) => task.taskId),
    [archivedTasks],
  );
  const { data: archivedTaskDetails = [], isLoading: isLoadingTasks } =
    useTaskSummaries(archivedTaskIds);
  const { restore, remove, runContextMenuAction } = useUnarchiveTask();

  useSetHeaderContent(
    <Text className="font-medium text-[13px]">Archived tasks</Text>,
  );

  const [branchNotFound, setBranchNotFound] =
    useState<BranchNotFoundPrompt | null>(null);

  const items = useMemo(
    () =>
      mergeArchivedWithTasks(archivedTasks, [
        ...listedTasks,
        ...archivedTaskDetails,
      ]),
    [archivedTasks, listedTasks, archivedTaskDetails],
  );

  const isLoading = isLoadingArchived || isLoadingTasks;

  const applyRestoreOutcome = (taskId: string, outcome: RestoreOutcome) => {
    if (outcome.kind === "restored") {
      const navigateToTaskId = outcome.navigateToTaskId;
      toast.success("Task unarchived", {
        action: navigateToTaskId
          ? {
              label: "View task",
              onClick: () =>
                void queryClient
                  .fetchQuery(taskDetailQuery(navigateToTaskId))
                  .then(openTask),
            }
          : undefined,
      });
    } else if (outcome.kind === "branch-not-found") {
      setBranchNotFound({ taskId, branchName: outcome.branchName });
    } else {
      toast.error(`Failed to unarchive task: ${outcome.message}`);
    }
  };

  const applyDeleteOutcome = (outcome: { kind: string; message?: string }) => {
    if (outcome.kind === "deleted") {
      toast.success("Task deleted");
    } else {
      toast.error(`Failed to delete task: ${outcome.message}`);
    }
  };

  const onUnarchive = async (taskId: string) => {
    const hasTask =
      items.find((i) => i.archived.taskId === taskId)?.task != null;
    applyRestoreOutcome(taskId, await restore(taskId, hasTask));
  };

  const onDelete = async (taskId: string) => {
    applyDeleteOutcome(await remove(taskId));
  };

  const handleContextMenu = async (
    item: ArchivedTaskWithDetails,
    e: React.MouseEvent,
  ) => {
    e.preventDefault();
    e.stopPropagation();

    const outcome = await runContextMenuAction(
      item.archived.taskId,
      item.task?.title ?? "Unknown task",
      item.task != null,
    );
    if (outcome.kind === "menu-error") {
      toast.error(`Context menu error: ${outcome.message}`);
    } else if (outcome.kind === "restore") {
      applyRestoreOutcome(item.archived.taskId, outcome.outcome);
    } else if (outcome.kind === "delete") {
      applyDeleteOutcome(outcome.outcome);
    }
  };

  const handleRecreateBranch = async () => {
    if (!branchNotFound) return;
    const { taskId } = branchNotFound;
    setBranchNotFound(null);
    const hasTask =
      items.find((i) => i.archived.taskId === taskId)?.task != null;
    applyRestoreOutcome(
      taskId,
      await restore(taskId, hasTask, { recreateBranch: true }),
    );
  };

  return (
    <ArchivedTasksViewPresentation
      items={items}
      isLoading={isLoading}
      branchNotFound={branchNotFound}
      onUnarchive={onUnarchive}
      onDelete={onDelete}
      onContextMenu={handleContextMenu}
      onBranchNotFoundClose={() => setBranchNotFound(null)}
      onRecreateBranch={handleRecreateBranch}
    />
  );
}
