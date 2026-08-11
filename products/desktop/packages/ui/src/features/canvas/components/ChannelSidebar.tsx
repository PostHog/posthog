import {
  ChatsCircleIcon,
  MagnifyingGlass,
  PackageIcon,
} from "@phosphor-icons/react";
import {
  type ChannelItemFilters,
  type ChannelItemSort,
  channelItemSources,
  DEFAULT_CHANNEL_ITEM_FILTERS,
  DEFAULT_CHANNEL_ITEM_SORT,
  filterChannelItems,
  hasActiveChannelItemFilters,
  sortChannelItems,
} from "@posthog/core/canvas/channelItems";
import {
  Button,
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
import { ChannelBackRow } from "@posthog/ui/features/canvas/components/ChannelBackRow";
import { ChannelFilterMenu } from "@posthog/ui/features/canvas/components/ChannelFilterMenu";
import { ChannelItemRow } from "@posthog/ui/features/canvas/components/ChannelItemRow";
import { ChannelsFab } from "@posthog/ui/features/canvas/components/ChannelsFab";
import { cnHeaderButton } from "@posthog/ui/features/canvas/components/channelHeaderButton";
import {
  type ChannelPageKey,
  channelPageLabel,
} from "@posthog/ui/features/canvas/components/channelPages";
import { useChannelItems } from "@posthog/ui/features/canvas/hooks/useChannelItems";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { PERSONAL_CHANNEL_NAME } from "@posthog/ui/features/canvas/hooks/useTaskChannels";
import { useCommandCenterStore } from "@posthog/ui/features/command-center/commandCenterStore";
import { placeTaskInCommandCenter } from "@posthog/ui/features/command-center/placeTaskInCommandCenter";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { SidebarItem } from "@posthog/ui/features/sidebar/components/SidebarItem";
import { useRenameTask } from "@posthog/ui/features/tasks/useTaskMutations";
import { logger } from "@posthog/ui/shell/logger";
import { useNavigate, useRouterState } from "@tanstack/react-router";
import { useMemo, useState } from "react";

const RECENTS_CAP = 30;
const log = logger.scope("channel-sidebar");

function RecentSectionHeader({
  searchOpen,
  onToggleSearch,
  query,
  onQueryChange,
  filters,
  onFiltersChange,
  sort,
  onSortChange,
  sources,
  showCreatedBy,
  filtersActive,
}: {
  searchOpen: boolean;
  onToggleSearch: () => void;
  query: string;
  onQueryChange: (value: string) => void;
  filters: ChannelItemFilters;
  onFiltersChange: (filters: ChannelItemFilters) => void;
  sort: ChannelItemSort;
  onSortChange: (sort: ChannelItemSort) => void;
  sources: readonly string[];
  /** False in #me, where every session is yours and the filter says nothing. */
  showCreatedBy: boolean;
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
        <ChannelFilterMenu
          filters={filters}
          onFiltersChange={onFiltersChange}
          sort={sort}
          onSortChange={onSortChange}
          sources={sources}
          showCreatedBy={showCreatedBy}
          active={filtersActive}
        />
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

  const [searchOpen, setSearchOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [rawFilters, setFilters] = useState<ChannelItemFilters>(
    DEFAULT_CHANNEL_ITEM_FILTERS,
  );
  const [sort, setSort] = useState<ChannelItemSort>(DEFAULT_CHANNEL_ITEM_SORT);
  // Every session in #me is yours, so the author filter has nothing to sort by.
  // The state survives a space switch, so the value is neutralised here as well
  // as hidden — otherwise "Other people" carried in from a shared space would
  // empty this list with no visible control to undo it.
  const { channels } = useChannels();
  const isPersonalChannel =
    channels.find((c) => c.id === channelId)?.name === PERSONAL_CHANNEL_NAME;
  const filters = useMemo<ChannelItemFilters>(
    () =>
      isPersonalChannel ? { ...rawFilters, createdBy: "anyone" } : rawFilters,
    [isPersonalChannel, rawFilters],
  );
  const filtersActive = hasActiveChannelItemFilters(filters);
  // The menu only offers sources the list holds, so it is built from everything
  // in the space rather than from what the current filters left behind — picking
  // one source must not be what removes the others from the menu.
  const sources = useMemo(() => channelItemSources(items), [items]);

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
  // is a request not to lose the thing: below the chosen order it would fall off
  // the end of the cap.
  const recentItems = useMemo(
    () =>
      sortChannelItems(
        filterChannelItems(items, { query, filters, me }),
        sort,
      ).slice(0, RECENTS_CAP),
    [items, query, filters, sort, me],
  );

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

  const commandCenterAssigner = (taskId: string, taskTitle: string) => () =>
    placeTaskInCommandCenter(taskId, taskTitle);

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
          ? commandCenterAssigner(item.id, item.title)
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
                filters={filters}
                onFiltersChange={setFilters}
                sort={sort}
                onSortChange={setSort}
                sources={sources}
                showCreatedBy={!isPersonalChannel}
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
