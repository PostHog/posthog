import {
  CaretDownIcon,
  CaretRightIcon,
  CaretUpIcon,
  ListMagnifyingGlassIcon,
  PlusIcon,
} from "@phosphor-icons/react";
import {
  type ChannelItemModel,
  channelItemSources,
  DEFAULT_CHANNEL_ITEM_FILTERS,
  filterChannelItems,
  groupChannelItems,
  hasActiveChannelItemFilters,
  sortChannelItems,
} from "@posthog/core/canvas/channelItems";
import type { ChannelPresence } from "@posthog/core/canvas/presence";
import {
  Autocomplete,
  AutocompleteList,
  Button,
  ContextMenu,
  ContextMenuContent,
  ContextMenuTrigger,
  cn,
  MenuLabel,
  Skeleton,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
import {
  commandCenterAssigner,
  isInCommandCenter,
} from "@posthog/ui/features/canvas/commandCenterAssign";
import { ChannelFilterMenu } from "@posthog/ui/features/canvas/components/ChannelFilterMenu";
import { SpaceHoverCard } from "@posthog/ui/features/canvas/components/ChannelItemHoverCard";
import { ChannelItemRow } from "@posthog/ui/features/canvas/components/ChannelItemRow";
import {
  ChannelActionItems,
  useChannelActions,
} from "@posthog/ui/features/canvas/components/ChannelsList";
import { CreateChannelModal } from "@posthog/ui/features/canvas/components/CreateChannelModal";
import { channelGlyph } from "@posthog/ui/features/canvas/components/channelGlyph";
import { PresenceAvatars } from "@posthog/ui/features/canvas/components/PresenceAvatars";
import { SidebarSearchInput } from "@posthog/ui/features/canvas/components/SidebarSearchHeader";
import { SpaceActionDialogs } from "@posthog/ui/features/canvas/components/SpaceActionDialogs";
import type { SpacePreviewPayload } from "@posthog/ui/features/canvas/components/SpacePreview";
import { WorkRowSurface } from "@posthog/ui/features/canvas/components/WorkRowSurface";
import { useBlockedSessionCount } from "@posthog/ui/features/canvas/hooks/useBlockedSessionCount";
import { useChannelItemSelection } from "@posthog/ui/features/canvas/hooks/useChannelItemSelection";
import { useChannelItemActions } from "@posthog/ui/features/canvas/hooks/useChannelItems";
import {
  type Channel,
  useChannels,
} from "@posthog/ui/features/canvas/hooks/useChannels";
import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import { useLocalDayStart } from "@posthog/ui/features/canvas/hooks/useLocalDayStart";
import {
  usePrefetchSpaceTasks,
  useSpacePresence,
} from "@posthog/ui/features/canvas/hooks/useRecentSpaceTasks";
import { useRecentWorkItems } from "@posthog/ui/features/canvas/hooks/useRecentWorkItems";
import { useSidebarSearchFocus } from "@posthog/ui/features/canvas/hooks/useSidebarSearchFocus";
import { useIsChannelUnread } from "@posthog/ui/features/canvas/hooks/useUnreadChannels";
import { useUnreadSessionCount } from "@posthog/ui/features/canvas/hooks/useUnreadSessionCount";
import { useCurrentChannelStore } from "@posthog/ui/features/canvas/stores/currentChannelStore";
import { useCommandCenterStore } from "@posthog/ui/features/command-center/commandCenterStore";
import { EditListItemAppearanceDialog } from "@posthog/ui/features/sidebar/components/EditListItemAppearanceDialog";
import { MarqueeOverlay } from "@posthog/ui/features/sidebar/components/MarqueeOverlay";
import { SidebarBulkActionBar } from "@posthog/ui/features/sidebar/components/SidebarBulkActionBar";
import { useSidebarStore } from "@posthog/ui/features/sidebar/sidebarStore";
import { useRenameTask } from "@posthog/ui/features/tasks/useTaskMutations";
import { ChromeBar } from "@posthog/ui/primitives/ChromeBar";
import {
  navigateToChannel,
  navigateToChannelDashboard,
  navigateToChannelTask,
  navigateToSpaces,
  navigateToTaskDetail,
} from "@posthog/ui/router/navigationBridge";
import { openTaskInput } from "@posthog/ui/router/useOpenTask";
import { track } from "@posthog/ui/shell/analytics";
import { logger } from "@posthog/ui/shell/logger";
import { useRouterState } from "@tanstack/react-router";
import {
  Fragment,
  type ReactNode,
  useCallback,
  useDeferredValue,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

const log = logger.scope("work-column");

const RECENT_COLLAPSED_COUNT = 5;

const SESSION_PREFETCH_DELAY_MS = 250;

// Recent leads with the newest work, so a pin neither floats a row to the top
// nor opens a section of its own. The row's badge is what says it is pinned.
const NO_PINNED_RUN = { pinnedRun: false } as const;

function SectionHeading({
  label,
  expanded,
  onToggle,
  trailing,
}: {
  label: string;
  expanded: boolean;
  onToggle: () => void;
  trailing?: ReactNode;
}) {
  const Caret = expanded ? CaretDownIcon : CaretRightIcon;
  return (
    <div className="flex items-center gap-1">
      <MenuLabel
        render={<button type="button" />}
        aria-expanded={expanded}
        onClick={onToggle}
        className="flex min-w-0 flex-1 items-center gap-1 rounded-sm py-1 font-semibold text-foreground/70 hover:text-foreground"
      >
        {label}
        <Caret size={11} className="shrink-0 opacity-60" />
      </MenuLabel>
      {trailing}
    </div>
  );
}

function IconAction({
  label,
  onClick,
  children,
}: {
  label: string;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Button
            variant="default"
            size="icon-sm"
            aria-label={label}
            onClick={onClick}
            className="text-muted-foreground"
          >
            {children}
          </Button>
        }
      />
      <TooltipContent side="right">{label}</TooltipContent>
    </Tooltip>
  );
}

export function SpaceRow({
  channel,
  isActive,
  unread,
  unreadSessions,
  blockedSessions,
  presence,
}: {
  channel: Channel;
  isActive: boolean;
  unread: boolean;
  unreadSessions: number;
  blockedSessions: number;
  presence: ChannelPresence | undefined;
}) {
  const people = presence?.people ?? [];
  const noun = useChannelsLayout() ? "space" : "channel";
  const channelActions = useChannelActions(channel);
  const { actions } = channelActions;
  const preview = useMemo<SpacePreviewPayload>(
    () => ({
      channel,
      unreadSessions,
      blockedSessions,
      actions: [
        {
          key: "new-session",
          label: "New session",
          icon: <PlusIcon size={14} />,
          onSelect: () => {
            track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
              action_type: "new_task_open",
              surface: "sidebar",
              channel_id: channel.id,
            });
            openTaskInput({ channelId: channel.id });
          },
        },
        ...actions,
      ],
    }),
    [channel, unreadSessions, blockedSessions, actions],
  );

  const prefetchSessions = usePrefetchSpaceTasks();
  const prefetchTimer = useRef<ReturnType<typeof setTimeout> | undefined>(
    undefined,
  );
  useEffect(() => () => clearTimeout(prefetchTimer.current), []);

  return (
    <>
      <SpaceHoverCard space={preview}>
        <ContextMenu>
          <ContextMenuTrigger
            render={
              <WorkRowSurface
                optionValue={channel.id}
                data-selected={isActive || undefined}
                onPointerEnter={() => {
                  clearTimeout(prefetchTimer.current);
                  prefetchTimer.current = setTimeout(
                    () => prefetchSessions(channel.id),
                    SESSION_PREFETCH_DELAY_MS,
                  );
                }}
                onPointerLeave={() => clearTimeout(prefetchTimer.current)}
                onClick={() => {
                  track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
                    action_type: "nav_click",
                    surface: "sidebar",
                    channel_id: channel.id,
                    nav_target: "space",
                  });
                  navigateToChannel(channel.id);
                }}
              >
                <span className="flex size-3.5 shrink-0 items-center justify-center text-muted-foreground">
                  {channelGlyph(channel.name, {
                    size: 13,
                    space: false,
                    personal: channel.channelType === "personal",
                    private: channel.channelType === "private",
                  })}
                </span>
                <span
                  className={cn(
                    "min-w-0 flex-1 truncate",
                    unread && "font-semibold",
                  )}
                >
                  {channel.name}
                </span>
                <span className="flex shrink-0 items-center gap-1.5">
                  {people.length > 0 && (
                    <PresenceAvatars
                      people={people}
                      liveUuids={presence?.liveUuids}
                    />
                  )}
                  {unread && !isActive && (
                    <span
                      role="img"
                      aria-label="Unread"
                      className="size-1.5 shrink-0 rounded-full bg-primary"
                    />
                  )}
                </span>
              </WorkRowSurface>
            }
          />
          <ContextMenuContent>
            <ChannelActionItems actions={preview.actions} kind="context" />
          </ContextMenuContent>
        </ContextMenu>
      </SpaceHoverCard>
      <SpaceActionDialogs
        channel={channel}
        noun={noun}
        actions={channelActions}
      />
    </>
  );
}

export function WorkColumn() {
  const [query, setQuery] = useState("");
  const [recentOpen, setRecentOpen] = useState(true);
  const [appearanceOpen, setAppearanceOpen] = useState(false);
  const searchRef = useRef<HTMLInputElement | null>(null);
  useSidebarSearchFocus(searchRef);
  const [recentExpanded, setRecentExpanded] = useState(false);
  const [spacesExpanded, setSpacesExpanded] = useState(true);
  const [createOpen, setCreateOpen] = useState(false);

  const { items, isLoading } = useRecentWorkItems();
  const { channels } = useChannels();
  const currentChannelId = useCurrentChannelStore((s) => s.currentChannelId);
  const isChannelUnread = useIsChannelUnread();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const activeKey = useMemo(() => {
    const dashboard = pathname.match(/\/dashboards\/([^/]+)$/);
    if (dashboard) return `canvas:${dashboard[1]}`;
    const task = pathname.match(/\/tasks\/([^/]+)$/);
    return task ? `task:${task[1]}` : null;
  }, [pathname]);
  const activeChannelId = pathname.startsWith("/spaces/")
    ? currentChannelId
    : null;

  const needle = query.trim().toLowerCase();
  const filters = useSidebarStore((state) => state.channelItemFilters);
  const setFilters = useSidebarStore((state) => state.setChannelItemFilters);
  const sort = useSidebarStore((state) => state.channelItemSort);
  const setSort = useSidebarStore((state) => state.setChannelItemSort);
  const grouping = useSidebarStore((state) => state.channelItemGrouping);
  const setGrouping = useSidebarStore((state) => state.setChannelItemGrouping);
  const client = useOptionalAuthenticatedClient();
  const { data: currentUser } = useCurrentUser({ client });
  const meUuid = currentUser?.uuid ?? null;
  const me = useMemo(() => ({ uuid: meUuid }), [meUuid]);
  const sources = useMemo(
    () => channelItemSources(items.map((entry) => entry.item)),
    [items],
  );
  const dayStart = useLocalDayStart();
  const matchingItems = useMemo(() => {
    const all = items.map((entry) => entry.item);
    const filtered = filterChannelItems(all, { query, filters, me });
    return sortChannelItems(filtered, sort, NO_PINNED_RUN);
  }, [items, query, filters, me, sort]);
  const spaceNameById = useMemo(
    () => new Map(channels.map((channel) => [channel.id, channel.name])),
    [channels],
  );
  const channelByKey = useMemo(
    () => new Map(items.map(({ item, channelId }) => [item.key, channelId])),
    [items],
  );
  const channelIdOf = useCallback(
    (item: ChannelItemModel) => channelByKey.get(item.key),
    [channelByKey],
  );
  const spaceOf = useCallback(
    (item: ChannelItemModel) => {
      const channelId = channelIdOf(item);
      const label = channelId ? spaceNameById.get(channelId) : undefined;
      return channelId && label ? { key: channelId, label } : null;
    },
    [channelIdOf, spaceNameById],
  );
  const sections = useMemo(
    () =>
      groupChannelItems(
        matchingItems,
        sort,
        new Date(dayStart),
        grouping,
        spaceOf,
        NO_PINNED_RUN,
      ),
    [matchingItems, sort, dayStart, grouping, spaceOf],
  );
  const starredSpaces = useMemo(
    () => [
      ...channels.filter((c) => c.channelType === "personal"),
      ...channels.filter((c) => c.channelType !== "personal" && c.starred),
    ],
    [channels],
  );

  const presenceBySpace = useSpacePresence();
  const unreadSessionCount = useUnreadSessionCount();
  const blockedSessionCount = useBlockedSessionCount();
  const open = useCallback(
    (item: ChannelItemModel) => {
      const channelId = channelIdOf(item);
      if (item.kind === "canvas") {
        if (channelId) navigateToChannelDashboard(channelId, item.id);
        return;
      }
      track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
        action_type: "open_task",
        surface: "sidebar",
        channel_id: channelId,
        task_id: item.id,
      });
      if (channelId) navigateToChannelTask(channelId, item.id);
      else navigateToTaskDetail(item.id);
    },
    [channelIdOf],
  );
  const actions = useChannelItemActions({ channelIdOf, open });

  const showAllRecent = useDeferredValue(recentExpanded || needle !== "");
  const recentRebuilding = showAllRecent !== (recentExpanded || needle !== "");
  const shownSections = useMemo(() => {
    if (showAllRecent) return sections;
    const out: typeof sections = [];
    let left = RECENT_COLLAPSED_COUNT;
    for (const section of sections) {
      if (left <= 0) break;
      out.push({ ...section, items: section.items.slice(0, left) });
      left -= section.items.length;
    }
    return out;
  }, [sections, showAllRecent]);
  const shownItems = useMemo(
    () => shownSections.flatMap((section) => section.items),
    [shownSections],
  );
  const canExpandRecent =
    needle === "" && matchingItems.length > RECENT_COLLAPSED_COUNT;
  const recentFills = recentOpen && recentExpanded;
  const {
    selectedTaskIds,
    clearSelection,
    bulkActions,
    archiveConfirm,
    marquee,
    listAnchorRef,
    onRowClick,
  } = useChannelItemSelection({ listItems: shownItems, activeKey, open });
  const commandCenterCells = useCommandCenterStore((state) => state.cells);
  const { renameTask } = useRenameTask();
  const [editingTaskId, setEditingTaskId] = useState<string | null>(null);

  const optionValues = useMemo(
    () => [
      ...shownItems
        .filter((item) => item.id !== editingTaskId)
        .map((item) => item.key),
      ...starredSpaces.map((channel) => channel.id),
    ],
    [shownItems, starredSpaces, editingTaskId],
  );

  const spaceNameFor = (item: ChannelItemModel): string | undefined =>
    spaceOf(item)?.label;

  return (
    <Autocomplete<string>
      inline
      open
      items={optionValues}
      filter={null}
      value={query}
      onValueChange={(value, eventDetails) => {
        if (
          eventDetails.reason === "input-change" &&
          typeof value === "string"
        ) {
          setQuery(value);
        }
      }}
    >
      <div className="flex h-full min-h-0 flex-col">
        <ChromeBar>
          <h2 className="font-bold text-base">Work</h2>
        </ChromeBar>
        <AutocompleteList className="sidebar-autocomplete-tree !max-h-none !px-2 !pt-2 !pb-2 flex min-h-0 flex-1 flex-col overflow-hidden">
          {/* The expanded list keeps a share of the column instead of all of it,
              so the spaces below it stay on screen. */}
          {/* Positioned and non-scrolling, because the marquee measures its band
              against this box and reads the rows inside it. */}
          <div
            ref={listAnchorRef}
            className={cn(
              "relative flex min-h-0 flex-col",
              recentFills && "flex-[3]",
            )}
          >
            <SectionHeading
              label="Recent"
              expanded={recentOpen}
              onToggle={() => setRecentOpen((value) => !value)}
            />
            {recentOpen && (
              <div className="flex items-center gap-1 px-1 pt-0.5 pb-1.5">
                <SidebarSearchInput
                  ref={searchRef}
                  query={query}
                  placeholder="Search recent…"
                  searchLabel="Search recent"
                  onClear={() => setQuery("")}
                  className="min-w-0 flex-1"
                />
                <ChannelFilterMenu
                  filters={filters}
                  onFilterChange={(key, value) =>
                    setFilters({ ...filters, [key]: value })
                  }
                  onClearFilters={() =>
                    setFilters(DEFAULT_CHANNEL_ITEM_FILTERS)
                  }
                  sort={sort}
                  onSortChange={setSort}
                  grouping={grouping}
                  onGroupingChange={setGrouping}
                  onEditAppearance={() => setAppearanceOpen(true)}
                  sources={sources}
                  showCreatedBy
                  showRunFilters
                  showKindFilter
                  groupings={["date", "space", "repository"]}
                  active={hasActiveChannelItemFilters(filters)}
                />
              </div>
            )}
            <div className="scroll-mask-8 flex min-h-0 flex-1 scroll-py-8 flex-col gap-px overflow-y-auto">
              {recentOpen &&
                (isLoading && items.length === 0 ? (
                  <div className="flex flex-col gap-2 px-2 py-1.5">
                    <Skeleton className="h-3.5 w-4/5" />
                    <Skeleton className="h-3.5 w-3/5" />
                    <Skeleton className="h-3.5 w-2/3" />
                  </div>
                ) : shownItems.length === 0 ? (
                  <p className="px-2 py-1 text-[12px] text-muted-foreground">
                    {needle || hasActiveChannelItemFilters(filters)
                      ? "Nothing here matches."
                      : "Sessions and canvases you open show up here."}
                  </p>
                ) : (
                  <div
                    className={cn(
                      "flex flex-col gap-px transition-opacity duration-150",
                      recentRebuilding && "pointer-events-none opacity-50",
                    )}
                  >
                    {shownSections.map((section, index) => (
                      <Fragment key={section.key}>
                        {section.label && (
                          <div
                            className={cn(
                              "px-2 pb-1 font-medium text-[11px] text-muted-foreground",
                              index === 0
                                ? "pt-1"
                                : "mt-2 border-border/70 border-t pt-2",
                            )}
                          >
                            {section.label}
                          </div>
                        )}
                        {section.items.map((item) => {
                          const inSelection =
                            item.kind === "task" &&
                            selectedTaskIds.includes(item.id);
                          return (
                            <ChannelItemRow
                              key={item.key}
                              item={item}
                              optionValue={item.key}
                              channelId={channelIdOf(item)}
                              spaceName={spaceNameFor(item)}
                              withPrStatus={false}
                              isActive={item.key === activeKey}
                              isSelected={inSelection}
                              actions={actions}
                              onClick={(event) => onRowClick(item, event)}
                              bulk={
                                inSelection && selectedTaskIds.length > 1
                                  ? {
                                      actions: bulkActions,
                                      onArchive: archiveConfirm.requestArchive,
                                    }
                                  : null
                              }
                              onContextMenuOpenChange={(open) => {
                                if (open && !inSelection) clearSelection();
                              }}
                              isEditing={
                                item.kind === "task" &&
                                editingTaskId === item.id
                              }
                              onRename={
                                item.kind === "task"
                                  ? () => setEditingTaskId(item.id)
                                  : undefined
                              }
                              onAddToCommandCenter={
                                isInCommandCenter(item, commandCenterCells)
                                  ? undefined
                                  : commandCenterAssigner(item)
                              }
                              onEditSubmit={
                                item.kind === "task"
                                  ? async (newTitle) => {
                                      setEditingTaskId(null);
                                      searchRef.current?.focus();
                                      try {
                                        await renameTask({
                                          taskId: item.id,
                                          currentTitle: item.title,
                                          newTitle,
                                        });
                                      } catch (error) {
                                        log.error(
                                          "Failed to rename task",
                                          error,
                                        );
                                      }
                                    }
                                  : undefined
                              }
                              onEditCancel={() => {
                                setEditingTaskId(null);
                                searchRef.current?.focus();
                              }}
                            />
                          );
                        })}
                      </Fragment>
                    ))}
                  </div>
                ))}
            </div>
            <MarqueeOverlay rect={marquee} />
            {recentOpen && canExpandRecent && (
              <button
                type="button"
                aria-expanded={recentExpanded}
                className="group/expand mt-0.5 flex h-6 w-full shrink-0 items-center justify-center gap-1 rounded-md text-[11px] text-muted-foreground transition-colors hover:bg-fill-hover hover:text-foreground"
                onClick={() => setRecentExpanded((value) => !value)}
              >
                {recentExpanded ? (
                  <>
                    <CaretUpIcon size={11} weight="bold" />
                    Show fewer
                  </>
                ) : (
                  <>
                    <CaretDownIcon size={11} weight="bold" />
                    {matchingItems.length - shownItems.length} more
                  </>
                )}
              </button>
            )}
          </div>

          <div
            className={cn(
              "mt-2 flex min-h-0 flex-col",
              recentFills ? "flex-[2]" : "flex-1",
            )}
          >
            <SectionHeading
              label="Spaces"
              expanded={spacesExpanded}
              onToggle={() => setSpacesExpanded((value) => !value)}
              trailing={
                <div className="flex items-center">
                  <IconAction
                    label="New space…"
                    onClick={() => setCreateOpen(true)}
                  >
                    <PlusIcon size={14} />
                  </IconAction>

                  <IconAction label="Browse spaces…" onClick={navigateToSpaces}>
                    <ListMagnifyingGlassIcon size={14} />
                  </IconAction>
                </div>
              }
            />
            {spacesExpanded && (
              <div className="scroll-mask-8 flex min-h-0 flex-1 scroll-py-8 flex-col gap-px overflow-y-auto">
                {starredSpaces.map((channel) => (
                  <SpaceRow
                    key={channel.id}
                    channel={channel}
                    isActive={channel.id === activeChannelId}
                    unread={isChannelUnread(channel.id)}
                    unreadSessions={unreadSessionCount(channel.id)}
                    blockedSessions={blockedSessionCount(channel.id)}
                    presence={presenceBySpace.get(channel.id)}
                  />
                ))}
                {starredSpaces.length <= 1 && needle === "" && (
                  <button
                    type="button"
                    className="mt-1 flex items-center gap-1.5 rounded-md border border-border border-dashed px-2 py-1.5 text-left font-medium text-[12px] text-muted-foreground transition-colors hover:border-foreground/40 hover:text-foreground"
                    onClick={navigateToSpaces}
                  >
                    <PlusIcon size={13} aria-hidden />
                    Add the spaces you work in
                  </button>
                )}
              </div>
            )}
          </div>
        </AutocompleteList>
        <SidebarBulkActionBar
          actions={bulkActions}
          onClearSelection={clearSelection}
          onArchive={archiveConfirm.requestArchive}
        />
      </div>
      {archiveConfirm.dialog}
      <CreateChannelModal open={createOpen} onOpenChange={setCreateOpen} />
      <EditListItemAppearanceDialog
        surface="sidebar"
        open={appearanceOpen}
        onOpenChange={setAppearanceOpen}
      />
    </Autocomplete>
  );
}
