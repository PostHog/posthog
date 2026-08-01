import {
  ChatsCircleIcon,
  FunnelSimple as FunnelSimpleIcon,
  MagnifyingGlass,
  PackageIcon,
} from "@phosphor-icons/react";
import type { CreatedByFilter } from "@posthog/core/canvas/channelItems";
import { filterChannelItems } from "@posthog/core/canvas/channelItems";
import { RUN_STATUS_FILTER_OPTIONS } from "@posthog/core/canvas/runStatus";
import {
  cn,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Input,
  MenuLabel,
  Skeleton,
  SkeletonText,
} from "@posthog/quill";
import { LOOPS_FLAG } from "@posthog/shared";
import type { TaskRunStatus } from "@posthog/shared/domain-types";
import { ChannelBackRow } from "@posthog/ui/features/canvas/components/ChannelBackRow";
import { ChannelItemRow } from "@posthog/ui/features/canvas/components/ChannelItemRow";
import { ChannelsFab } from "@posthog/ui/features/canvas/components/ChannelsFab";
import {
  type ChannelPageKey,
  channelPageIcon,
  channelPageLabel,
} from "@posthog/ui/features/canvas/components/channelPages";
import { useChannelItems } from "@posthog/ui/features/canvas/hooks/useChannelItems";
import { useCommandCenterStore } from "@posthog/ui/features/command-center/commandCenterStore";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { SidebarItem } from "@posthog/ui/features/sidebar/components/SidebarItem";
import { useTaskContextMenu } from "@posthog/ui/features/tasks/useTaskContextMenu";
import { useRenameTask } from "@posthog/ui/features/tasks/useTaskMutations";
import { useTasks } from "@posthog/ui/features/tasks/useTasks";
import { navigateToCommandCenter } from "@posthog/ui/router/navigationBridge";
import { logger } from "@posthog/ui/shell/logger";
import { useNavigate, useRouterState } from "@tanstack/react-router";
import { useMemo, useState } from "react";

const CREATED_BY_OPTIONS: readonly { value: CreatedByFilter; label: string }[] =
  [
    { value: "anyone", label: "Anyone" },
    { value: "me", label: "Me" },
    { value: "others", label: "Other people" },
  ] as const;

const HEADER_ICON_BUTTON_CLASS =
  "flex size-5 shrink-0 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-fill-hover hover:text-foreground";

const cnHeaderButton = (active: boolean) =>
  cn(HEADER_ICON_BUTTON_CLASS, active && "bg-fill-selected text-foreground");

const RECENTS_CAP = 30;
const log = logger.scope("channel-sidebar");

function RecentSectionHeader({
  searchOpen,
  onToggleSearch,
  query,
  onQueryChange,
  createdByFilter,
  onCreatedByChange,
  statusFilter,
  onStatusChange,
  filtersActive,
}: {
  searchOpen: boolean;
  onToggleSearch: () => void;
  query: string;
  onQueryChange: (value: string) => void;
  createdByFilter: CreatedByFilter;
  onCreatedByChange: (value: CreatedByFilter) => void;
  statusFilter: TaskRunStatus | null;
  onStatusChange: (value: TaskRunStatus | null) => void;
  filtersActive: boolean;
}) {
  return (
    <>
      <div className="flex items-center gap-0.5 pr-1">
        <div className="min-w-0 flex-1">
          <MenuLabel>Recent</MenuLabel>
        </div>
        <button
          type="button"
          aria-label="Search"
          aria-pressed={searchOpen}
          onClick={onToggleSearch}
          className={cnHeaderButton(searchOpen)}
        >
          <MagnifyingGlass size={12} />
        </button>
        <DropdownMenu>
          <DropdownMenuTrigger
            render={
              <button
                type="button"
                aria-label="Filter"
                className={cnHeaderButton(filtersActive)}
              >
                <FunnelSimpleIcon size={12} />
              </button>
            }
          />
          <DropdownMenuContent
            align="end"
            side="bottom"
            sideOffset={6}
            className="min-w-fit"
          >
            <MenuLabel>Created by</MenuLabel>
            <DropdownMenuRadioGroup
              value={createdByFilter}
              onValueChange={(value) =>
                onCreatedByChange(value as CreatedByFilter)
              }
            >
              {CREATED_BY_OPTIONS.map((option) => (
                <DropdownMenuRadioItem key={option.value} value={option.value}>
                  {option.label}
                </DropdownMenuRadioItem>
              ))}
            </DropdownMenuRadioGroup>
            <DropdownMenuSeparator />
            <MenuLabel>Status</MenuLabel>
            <DropdownMenuRadioGroup
              value={statusFilter ?? "any"}
              onValueChange={(value) =>
                onStatusChange(
                  value === "any" ? null : (value as TaskRunStatus),
                )
              }
            >
              {RUN_STATUS_FILTER_OPTIONS.map((option) => (
                <DropdownMenuRadioItem
                  key={option.value ?? "any"}
                  value={option.value ?? "any"}
                >
                  {option.label}
                </DropdownMenuRadioItem>
              ))}
            </DropdownMenuRadioGroup>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
      {searchOpen && (
        <div className="px-1 pb-1">
          <Input
            autoFocus
            value={query}
            onChange={(event) => onQueryChange(event.target.value)}
            placeholder="Search…"
            aria-label="Search recent items"
            className="h-6 text-[12px]"
          />
        </div>
      )}
    </>
  );
}

// Varied widths, as percentages, so the loading state reads as the list it
// becomes rather than a stack of identical bars.
const SKELETON_ROW_WIDTHS = [60, 80, 40, 75, 50, 66] as const;

function ChannelItemsSkeleton() {
  return (
    <div aria-hidden className="flex flex-col gap-px">
      {/* Stands in for the "Recent" MenuLabel, so it carries that label's scale. */}
      <SkeletonText
        lines={1}
        maxWidth={100}
        className="mx-2 mt-1.5 mb-1 w-12 text-xs"
      />
      {SKELETON_ROW_WIDTHS.map((width) => (
        <div key={width} className="flex items-center gap-2 px-2 py-1.5">
          <Skeleton className="size-4 shrink-0 rounded" />
          {/* SkeletonText sizes its bar off the line it stands in — text-[13px]
              is a row's own type scale, so the placeholder is the height of the
              title it becomes rather than a fixed pill. */}
          <SkeletonText
            lines={1}
            maxWidth={width}
            className="min-w-0 flex-1 text-[13px] leading-snug"
          />
        </div>
      ))}
    </div>
  );
}

/** `ready` is the list itself, whether or not the filters leave any rows in it. */
type ListState = "unavailable" | "loading" | "empty" | "ready";

/**
 * What the list shows, decided in one place. These were four conditions spread
 * across the render tree, which let a cold load draw the skeleton and the "No
 * matches" empty state at the same time.
 *
 * `narrowed` — a filter, or an open search box — is what makes no items mean
 * "nothing matches" rather than "nothing here".
 */
function listStateOf({
  channelMissing,
  isLoading,
  itemCount,
  narrowed,
}: {
  channelMissing: boolean;
  isLoading: boolean;
  itemCount: number;
  narrowed: boolean;
}): ListState {
  if (channelMissing) return "unavailable";
  if (isLoading && itemCount === 0) return "loading";
  if (itemCount === 0 && !narrowed) return "empty";
  return "ready";
}

/**
 * The channel pane of the sidebar slider: the way back to the channel list,
 * the channel's sections, then its pinned and recent tasks & canvases.
 */
export function ChannelSidebar({ channelId }: { channelId: string }) {
  const navigate = useNavigate();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const loopsEnabled = useFeatureFlag(LOOPS_FLAG, import.meta.env.DEV);

  const { items, actions, me, isLoading, channelMissing } =
    useChannelItems(channelId);
  const { showContextMenu, editingTaskId, setEditingTaskId } =
    useTaskContextMenu();
  const { renameTask } = useRenameTask();
  const commandCenterCells = useCommandCenterStore((state) => state.cells);
  const assignTaskToCommandCenter = useCommandCenterStore(
    (state) => state.assignTask,
  );
  const { data: allTasks = [] } = useTasks({ showAllUsers: true });
  const allTaskIds = useMemo(
    () => new Set(allTasks.map((task) => task.id)),
    [allTasks],
  );

  const [searchOpen, setSearchOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [createdByFilter, setCreatedByFilter] =
    useState<CreatedByFilter>("anyone");
  const [statusFilter, setStatusFilter] = useState<TaskRunStatus | null>(null);
  const filtersActive = createdByFilter !== "anyone" || statusFilter !== null;

  const base = `/website/${channelId}`;
  // Activeness is a key comparison rather than a flag baked into each item, so
  // navigating doesn't rebuild the list.
  const activeKey = useMemo(() => {
    const dashboard = pathname.match(/\/dashboards\/([^/]+)$/);
    if (dashboard) return `canvas:${dashboard[1]}`;
    const task = pathname.match(/\/tasks\/([^/]+)$/);
    return task ? `task:${task[1]}` : null;
  }, [pathname]);

  const pinnedItems = useMemo(() => items.filter((i) => i.pinned), [items]);
  const recentItems = useMemo(
    () =>
      filterChannelItems(
        items.filter((i) => !i.pinned),
        { query, createdBy: createdByFilter, status: statusFilter, me },
      ).slice(0, RECENTS_CAP),
    [items, query, createdByFilter, statusFilter, me],
  );

  const narrowed = filtersActive || searchOpen;
  const listState = listStateOf({
    channelMissing,
    isLoading,
    itemCount: items.length,
    narrowed,
  });
  // The list's two sections, which only exist once there are items. With
  // everything pinned there's nothing left to list — but keep the header while
  // it's narrowed, so you can undo whatever emptied it.
  const showPinned = listState === "ready" && pinnedItems.length > 0;
  const showRecent =
    listState === "ready" && (items.some((i) => !i.pinned) || narrowed);

  const taskRow = (item: (typeof items)[number]) => (
    <ChannelItemRow
      key={item.key}
      item={item}
      isActive={item.key === activeKey}
      actions={actions}
      isEditing={item.kind === "task" && editingTaskId === item.id}
      onContextMenu={
        item.kind === "task"
          ? (event) =>
              void showContextMenu(item, event, {
                isPinned: item.pinned,
                isInCommandCenter: commandCenterCells.includes(item.id),
                hasEmptyCommandCenterCell: commandCenterCells.some(
                  (taskId) => taskId == null || !allTaskIds.has(taskId),
                ),
                showArchivePrior: false,
                onTogglePin: () => actions.togglePin(item),
                onArchive: () => actions.archive(item),
                onAddToCommandCenter: () => {
                  const cellIndex = commandCenterCells.findIndex(
                    (taskId) => taskId == null || !allTaskIds.has(taskId),
                  );
                  if (cellIndex === -1) return;
                  assignTaskToCommandCenter(cellIndex, item.id);
                  navigateToCommandCenter();
                },
              })
          : undefined
      }
      onEditSubmit={
        item.kind === "task"
          ? async (newTitle) => {
              setEditingTaskId(null);
              try {
                await renameTask({
                  taskId: item.id,
                  currentTitle: item.title,
                  newTitle,
                });
              } catch (error) {
                log.error("Failed to rename task", error);
              }
            }
          : undefined
      }
      onEditCancel={() => setEditingTaskId(null)}
    />
  );

  // Label and icon come from the shared space-page table, so a sidebar row and
  // the header breadcrumb for the same page can never disagree.
  const sectionRow = (
    page: ChannelPageKey,
    to: string,
    onClick: () => void,
  ) => (
    <SidebarItem
      depth={0}
      icon={channelPageIcon(page, { size: 16 })}
      label={channelPageLabel(page)}
      isActive={pathname === to}
      onClick={onClick}
    />
  );

  return (
    <div className="flex h-full min-h-0 flex-col">
      <ChannelBackRow channelId={channelId} />

      <div className="flex flex-col gap-px px-2 pt-2">
        {sectionRow(
          "home",
          base,
          () =>
            void navigate({ to: "/website/$channelId", params: { channelId } }),
        )}
        {sectionRow(
          "context",
          `${base}/context`,
          () =>
            void navigate({
              to: "/website/$channelId/context",
              params: { channelId },
            }),
        )}
        {loopsEnabled &&
          sectionRow(
            "loops",
            `${base}/loops`,
            () =>
              void navigate({
                to: "/website/$channelId/loops",
                params: { channelId },
              }),
          )}
        {sectionRow(
          "artifacts",
          `${base}/artifacts`,
          () =>
            void navigate({
              to: "/website/$channelId/artifacts",
              params: { channelId },
            }),
        )}
      </div>

      {/* Relative so the FAB can float over the list. */}
      <div className="relative mt-2 min-h-0 flex-1">
        <div
          aria-busy={isLoading}
          className="scroll-mask-4 h-full overflow-y-auto px-2 pb-2"
        >
          {listState === "loading" && <ChannelItemsSkeleton />}

          {listState === "unavailable" && (
            <Empty className="border-0 py-6">
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <PackageIcon size={18} />
                </EmptyMedia>
                <EmptyTitle>Space unavailable</EmptyTitle>
                <EmptyDescription>
                  It may have been deleted, or belong to another project.
                </EmptyDescription>
              </EmptyHeader>
            </Empty>
          )}

          {showPinned && (
            <>
              <MenuLabel>Pinned</MenuLabel>
              <div className="flex flex-col gap-px">
                {pinnedItems.map(taskRow)}
              </div>
            </>
          )}

          {showRecent && (
            <>
              <RecentSectionHeader
                searchOpen={searchOpen}
                onToggleSearch={() => {
                  if (searchOpen) setQuery("");
                  setSearchOpen(!searchOpen);
                }}
                query={query}
                onQueryChange={setQuery}
                createdByFilter={createdByFilter}
                onCreatedByChange={setCreatedByFilter}
                statusFilter={statusFilter}
                onStatusChange={setStatusFilter}
                filtersActive={filtersActive}
              />
              {recentItems.length > 0 ? (
                <div className="flex flex-col gap-px">
                  {recentItems.map(taskRow)}
                </div>
              ) : (
                <Empty className="border-0 py-6">
                  <EmptyHeader>
                    <EmptyMedia variant="icon">
                      <MagnifyingGlass size={18} />
                    </EmptyMedia>
                    <EmptyTitle>No matches</EmptyTitle>
                    <EmptyDescription>
                      Try a different search or clear the filters.
                    </EmptyDescription>
                  </EmptyHeader>
                </Empty>
              )}
            </>
          )}

          {listState === "empty" && (
            <Empty className="border-0 py-6">
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <ChatsCircleIcon size={18} />
                </EmptyMedia>
                <EmptyTitle>Nothing here yet</EmptyTitle>
                <EmptyDescription>
                  Tasks and canvases you create in this space show up here.
                </EmptyDescription>
              </EmptyHeader>
            </Empty>
          )}
        </div>
        <ChannelsFab channelId={channelId} />
      </div>
    </div>
  );
}
