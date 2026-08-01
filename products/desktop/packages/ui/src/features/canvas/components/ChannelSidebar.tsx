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
  Button,
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
  channelPageLabel,
} from "@posthog/ui/features/canvas/components/channelPages";
import { useChannelItems } from "@posthog/ui/features/canvas/hooks/useChannelItems";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { PERSONAL_CHANNEL_NAME } from "@posthog/ui/features/canvas/hooks/useTaskChannels";
import { useCommandCenterStore } from "@posthog/ui/features/command-center/commandCenterStore";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { SidebarItem } from "@posthog/ui/features/sidebar/components/SidebarItem";
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

// The header's icon buttons are quill's ghost button at the 20px scale; only the
// sticky state is ours, because quill styles the transient open state (hover,
// popup) but has no notion of "search is showing" or "a filter is applied".
const cnHeaderButton = (active: boolean) =>
  cn("text-muted-foreground", active && "bg-fill-selected text-foreground");

const RECENTS_CAP = 30;
const log = logger.scope("channel-sidebar");

function RecentSectionHeader({
  searchOpen,
  onToggleSearch,
  query,
  onQueryChange,
  createdByFilter,
  onCreatedByChange,
  showCreatedBy,
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
  /** False in #me, where every session is yours and the filter says nothing. */
  showCreatedBy: boolean;
  statusFilter: TaskRunStatus | null;
  onStatusChange: (value: TaskRunStatus | null) => void;
  filtersActive: boolean;
}) {
  return (
    <>
      <div className="flex items-center gap-0.5">
        <div className="min-w-0 flex-1">
          <MenuLabel>Sessions</MenuLabel>
        </div>
        <Button
          variant="default"
          size="icon-xs"
          aria-label="Search"
          aria-pressed={searchOpen}
          onClick={onToggleSearch}
          className={cnHeaderButton(searchOpen)}
        >
          <MagnifyingGlass size={12} />
        </Button>
        <DropdownMenu>
          <DropdownMenuTrigger
            render={
              <Button
                variant="default"
                size="icon-xs"
                aria-label="Filter"
                className={cnHeaderButton(filtersActive)}
              >
                <FunnelSimpleIcon size={12} />
              </Button>
            }
          />
          <DropdownMenuContent
            align="end"
            side="bottom"
            sideOffset={6}
            className="min-w-fit"
          >
            {/* #me holds only your own sessions, so "created by" can only ever
                answer "you" — the whole group is dropped rather than shown with
                two options that empty the list. */}
            {showCreatedBy && (
              <>
                <MenuLabel>Created by</MenuLabel>
                <DropdownMenuRadioGroup
                  value={createdByFilter}
                  onValueChange={(value) =>
                    onCreatedByChange(value as CreatedByFilter)
                  }
                >
                  {CREATED_BY_OPTIONS.map((option) => (
                    <DropdownMenuRadioItem
                      key={option.value}
                      value={option.value}
                    >
                      {option.label}
                    </DropdownMenuRadioItem>
                  ))}
                </DropdownMenuRadioGroup>
                <DropdownMenuSeparator />
              </>
            )}
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
            aria-label="Search sessions"
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
      {/* Stands in for the "Sessions" MenuLabel, so it carries that label's scale. */}
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
  // Inline rename is the only thing left of the old native-menu hook here: the
  // row's menu is a quill one now, so this surface no longer reaches into the
  // main process to draw it.
  const [editingTaskId, setEditingTaskId] = useState<string | null>(null);
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
  // Every session in #me is yours, so the author filter has nothing to sort by.
  // The state survives a space switch, so the value is neutralised here as well
  // as hidden — otherwise "Other people" carried in from a shared space would
  // empty this list with no visible control to undo it.
  const { channels } = useChannels();
  const isPersonalChannel =
    channels.find((c) => c.id === channelId)?.name === PERSONAL_CHANNEL_NAME;
  const createdBy: CreatedByFilter = isPersonalChannel
    ? "anyone"
    : createdByFilter;
  const filtersActive = createdBy !== "anyone" || statusFilter !== null;

  const base = `/website/${channelId}`;
  // Activeness is a key comparison rather than a flag baked into each item, so
  // navigating doesn't rebuild the list.
  const activeKey = useMemo(() => {
    const dashboard = pathname.match(/\/dashboards\/([^/]+)$/);
    if (dashboard) return `canvas:${dashboard[1]}`;
    const task = pathname.match(/\/tasks\/([^/]+)$/);
    return task ? `task:${task[1]}` : null;
  }, [pathname]);

  // One list, pins included — a pin is a mark on a session, not a different kind
  // of thing, and the row's own badge says so. They sort to the top because a pin
  // is a request not to lose the thing: below the recency order it would fall off
  // the end of the cap.
  const recentItems = useMemo(() => {
    const matching = filterChannelItems(items, {
      query,
      createdBy,
      status: statusFilter,
      me,
    });
    return [
      ...matching.filter((i) => i.pinned),
      ...matching.filter((i) => !i.pinned),
    ].slice(0, RECENTS_CAP);
  }, [items, query, createdBy, statusFilter, me]);

  const narrowed = filtersActive || searchOpen;
  const listState = listStateOf({
    channelMissing,
    isLoading,
    itemCount: items.length,
    narrowed,
  });
  // The one section, which only exists once there are items — but its header
  // stays while the list is narrowed, so you can undo whatever emptied it.
  const showRecent = listState === "ready";

  // The first free command-centre cell, or nothing if every cell is taken by a
  // task that still exists.
  const commandCenterAssigner = (taskId: string) => {
    const cellIndex = commandCenterCells.findIndex(
      (cellTaskId) => cellTaskId == null || !allTaskIds.has(cellTaskId),
    );
    if (cellIndex === -1) return undefined;
    return () => {
      assignTaskToCommandCenter(cellIndex, taskId);
      navigateToCommandCenter();
    };
  };

  const taskRow = (item: (typeof items)[number]) => (
    <ChannelItemRow
      key={item.key}
      item={item}
      channelId={channelId}
      isActive={item.key === activeKey}
      actions={actions}
      isEditing={item.kind === "task" && editingTaskId === item.id}
      onRename={
        item.kind === "task" ? () => setEditingTaskId(item.id) : undefined
      }
      // Undefined disables the menu item: a full command centre has nowhere to
      // put the task, and an action that silently does nothing is worse than a
      // greyed-out one.
      onAddToCommandCenter={
        item.kind === "task" && !commandCenterCells.includes(item.id)
          ? commandCenterAssigner(item.id)
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

  // Label comes from the shared space-page table, so a sidebar row and the
  // header breadcrumb for the same page can never disagree. No icon: this is a
  // four-row list of words, and glyphs here only compete with the status dots
  // in the sessions list below for the eye's attention.
  const sectionRow = (
    page: ChannelPageKey,
    to: string,
    onClick: () => void,
  ) => (
    <SidebarItem
      depth={0}
      label={channelPageLabel(page)}
      isActive={pathname === to}
      onClick={onClick}
    />
  );

  return (
    <div className="flex h-full min-h-0 flex-col border-border border-t pt-1">
      <ChannelBackRow channelId={channelId} />

      <div className="flex flex-col gap-px px-2 pt-2">
        {/* Starting a session is what you came here to do, so it leads the
            pane's list of places rather than hiding behind one of them. */}
        <SidebarItem
          depth={0}
          label="New session"
          isActive={pathname === `${base}/new`}
          onClick={() =>
            void navigate({
              to: "/website/$channelId/new",
              params: { channelId },
            })
          }
        />
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
                createdByFilter={createdBy}
                onCreatedByChange={setCreatedByFilter}
                showCreatedBy={!isPersonalChannel}
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
