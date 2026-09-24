import {
  ListMagnifyingGlassIcon,
  MagnifyingGlassIcon,
  PlusIcon,
} from "@phosphor-icons/react";
import {
  type ChannelItemModel,
  channelItemSources,
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
import { SpaceActionDialogs } from "@posthog/ui/features/canvas/components/SpaceActionDialogs";
import type { SpacePreviewPayload } from "@posthog/ui/features/canvas/components/SpacePreview";
import { WorkRowSurface } from "@posthog/ui/features/canvas/components/WorkRowSurface";
import { WorkSearchField } from "@posthog/ui/features/canvas/components/work/WorkSearchField";
import { WorkSection } from "@posthog/ui/features/canvas/components/work/WorkSection";
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
import { useIsChannelUnread } from "@posthog/ui/features/canvas/hooks/useUnreadChannels";
import { useUnreadSessionCount } from "@posthog/ui/features/canvas/hooks/useUnreadSessionCount";
import { useWorkSectionLayout } from "@posthog/ui/features/canvas/hooks/useWorkSectionLayout";
import { useCurrentChannelStore } from "@posthog/ui/features/canvas/stores/currentChannelStore";
import { useSidebarSearchStore } from "@posthog/ui/features/canvas/stores/sidebarSearchStore";
import type { WorkSectionId } from "@posthog/ui/features/canvas/workSectionLayout";
import {
  formatHotkey,
  SHORTCUTS,
} from "@posthog/ui/features/command/keyboard-shortcuts";
import { useCommandCenterStore } from "@posthog/ui/features/command-center/commandCenterStore";
import { EditListItemAppearanceDialog } from "@posthog/ui/features/sidebar/components/EditListItemAppearanceDialog";
import { MarqueeOverlay } from "@posthog/ui/features/sidebar/components/MarqueeOverlay";
import { SidebarBulkActionBar } from "@posthog/ui/features/sidebar/components/SidebarBulkActionBar";
import {
  DEFAULT_SIDEBAR_CHANNEL_ITEM_FILTERS,
  useSidebarStore,
} from "@posthog/ui/features/sidebar/sidebarStore";
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
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

const log = logger.scope("work-column");

const SESSION_PREFETCH_DELAY_MS = 250;

const NO_PINNED_RUN = { pinnedRun: false } as const;

const SECTIONS: Record<WorkSectionId, { key: string; label: string }> = {
  pinned: { key: "work-pinned", label: "Pinned" },
  recent: { key: "work-recent", label: "Recent" },
  spaces: { key: "work-spaces", label: "Spaces" },
};

function isPinnedTask(item: ChannelItemModel): boolean {
  return item.kind === "task" && item.pinned;
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
            size="icon-xs"
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
  const [searchOpen, setSearchOpen] = useState(false);
  const [appearanceOpen, setAppearanceOpen] = useState(false);
  const searchRef = useRef<HTMLInputElement | null>(null);
  const columnRef = useRef<HTMLDivElement | null>(null);
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
  const collapsedSections = useSidebarStore((state) => state.collapsedSections);
  const toggleSection = useSidebarStore((state) => state.toggleSection);
  const workSectionHeights = useSidebarStore(
    (state) => state.workSectionHeights,
  );
  const setWorkSectionHeights = useSidebarStore(
    (state) => state.setWorkSectionHeights,
  );
  const client = useOptionalAuthenticatedClient();
  const { data: currentUser } = useCurrentUser({ client });
  const meUuid = currentUser?.uuid ?? null;
  const me = useMemo(() => ({ uuid: meUuid }), [meUuid]);
  const sources = useMemo(
    () => channelItemSources(items.map((entry) => entry.item)),
    [items],
  );
  const dayStart = useLocalDayStart();
  const pinnedItems = useMemo(
    () => items.map((entry) => entry.item).filter(isPinnedTask),
    [items],
  );
  const matchingItems = useMemo(() => {
    const unpinned = items
      .map((entry) => entry.item)
      .filter((item) => !isPinnedTask(item));
    const filtered = filterChannelItems(unpinned, { query, filters, me });
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
  const recentSections = useMemo(
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
  const recentItems = useMemo(
    () => recentSections.flatMap((section) => section.items),
    [recentSections],
  );
  const starredSpaces = useMemo(
    () => [
      ...channels.filter((c) => c.channelType === "personal"),
      ...channels.filter((c) => c.channelType !== "personal" && c.starred),
    ],
    [channels],
  );

  const isOpen = (id: WorkSectionId) =>
    !collapsedSections.has(SECTIONS[id].key);
  const pinnedOpen = isOpen("pinned");
  const recentOpen = isOpen("recent");
  const spacesOpen = isOpen("spaces");
  const hasPinned = pinnedItems.length > 0;
  const layoutSections = useMemo(
    () => [
      ...(hasPinned ? [{ id: "pinned" as const, open: pinnedOpen }] : []),
      { id: "recent" as const, open: recentOpen },
      { id: "spaces" as const, open: spacesOpen },
    ],
    [hasPinned, pinnedOpen, recentOpen, spacesOpen],
  );
  const layout = useWorkSectionLayout({
    sections: layoutSections,
    preferred: workSectionHeights,
    onPreferredChange: setWorkSectionHeights,
  });

  const searchVisible = recentOpen && (searchOpen || query !== "");
  const openSearch = useCallback(() => {
    if (!recentOpen) toggleSection(SECTIONS.recent.key);
    setSearchOpen(true);
    searchRef.current?.select();
  }, [recentOpen, toggleSection]);
  const closeSearch = () => {
    setQuery("");
    setSearchOpen(false);
  };

  useEffect(() => {
    if (searchVisible) searchRef.current?.focus();
  }, [searchVisible]);

  const focusRequest = useSidebarSearchStore((state) => state.focusRequest);
  useEffect(() => {
    if (focusRequest === 0 || columnRef.current?.closest("[inert]")) return;
    if (useSidebarSearchStore.getState().claimFocus(focusRequest)) openSearch();
  }, [focusRequest, openSearch]);

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

  const listItems = useMemo(
    () => [
      ...(hasPinned && pinnedOpen ? pinnedItems : []),
      ...(recentOpen ? recentItems : []),
    ],
    [hasPinned, pinnedOpen, pinnedItems, recentOpen, recentItems],
  );
  const {
    selectedTaskIds,
    clearSelection,
    bulkActions,
    archiveConfirm,
    marquee,
    listAnchorRef,
    onRowClick,
  } = useChannelItemSelection({ listItems, activeKey, open });
  const commandCenterCells = useCommandCenterStore((state) => state.cells);
  const { renameTask } = useRenameTask();
  const [editingTaskId, setEditingTaskId] = useState<string | null>(null);

  const measureArea = layout.measureRefs.area;
  const sectionsRef = useCallback(
    (element: HTMLDivElement | null) => {
      listAnchorRef.current = element;
      return measureArea(element);
    },
    [listAnchorRef, measureArea],
  );

  const optionValues = useMemo(
    () => [
      ...listItems
        .filter((item) => item.id !== editingTaskId)
        .map((item) => item.key),
      ...(spacesOpen ? starredSpaces.map((channel) => channel.id) : []),
    ],
    [listItems, spacesOpen, starredSpaces, editingTaskId],
  );

  const spaceNameFor = (item: ChannelItemModel): string | undefined =>
    spaceOf(item)?.label;

  const renderItemRow = (
    item: ChannelItemModel,
    { showPinBadge }: { showPinBadge: boolean },
  ) => {
    const inSelection =
      item.kind === "task" && selectedTaskIds.includes(item.id);
    return (
      <ChannelItemRow
        key={item.key}
        item={item}
        optionValue={item.key}
        channelId={channelIdOf(item)}
        spaceName={spaceNameFor(item)}
        showPinBadge={showPinBadge}
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
        onContextMenuOpenChange={(menuOpen) => {
          if (menuOpen && !inSelection) clearSelection();
        }}
        isEditing={item.kind === "task" && editingTaskId === item.id}
        onRename={
          item.kind === "task" ? () => setEditingTaskId(item.id) : undefined
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
                  log.error("Failed to rename task", error);
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
  };

  const renderRecent = () => {
    if (isLoading && items.length === 0) {
      return (
        <div className="flex flex-col gap-2 px-2 py-1.5">
          <Skeleton className="h-3.5 w-4/5" />
          <Skeleton className="h-3.5 w-3/5" />
          <Skeleton className="h-3.5 w-2/3" />
        </div>
      );
    }
    if (recentItems.length === 0) {
      return (
        <p className="px-2 py-1 text-[12px] text-muted-foreground">
          {needle ||
          hasActiveChannelItemFilters(
            filters,
            DEFAULT_SIDEBAR_CHANNEL_ITEM_FILTERS,
          )
            ? "Nothing here matches."
            : "Sessions and canvases you open show up here."}
        </p>
      );
    }
    return recentSections.map((section, index) => (
      <Fragment key={section.key}>
        {section.label && (
          <div
            className={cn(
              "px-2 pb-1 font-medium text-[11px] text-muted-foreground",
              index === 0 ? "pt-1" : "mt-2 border-border/70 border-t pt-2",
            )}
          >
            {section.label}
          </div>
        )}
        {section.items.map((item) =>
          renderItemRow(item, { showPinBadge: true }),
        )}
      </Fragment>
    ));
  };

  const spacesBody = (
    <>
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
    </>
  );

  const filterMenu = (
    <ChannelFilterMenu
      filters={filters}
      onFilterChange={(key, value) => setFilters({ ...filters, [key]: value })}
      onClearFilters={() => setFilters(DEFAULT_SIDEBAR_CHANNEL_ITEM_FILTERS)}
      defaultFilters={DEFAULT_SIDEBAR_CHANNEL_ITEM_FILTERS}
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
      active={hasActiveChannelItemFilters(
        filters,
        DEFAULT_SIDEBAR_CHANNEL_ITEM_FILTERS,
      )}
    />
  );

  const sectionContent: Record<
    WorkSectionId,
    {
      count: number;
      actions?: ReactNode;
      replaceHeading?: ReactNode;
      body: ReactNode;
    }
  > = {
    pinned: {
      count: pinnedItems.length,
      body: pinnedItems.map((item) =>
        renderItemRow(item, { showPinBadge: false }),
      ),
    },
    recent: {
      count: recentItems.length,
      actions: (
        <>
          {!searchVisible && (
            <IconAction
              label={`Search recent (${formatHotkey(SHORTCUTS.FOCUS_SIDEBAR_SEARCH)})`}
              onClick={openSearch}
            >
              <MagnifyingGlassIcon size={14} />
            </IconAction>
          )}
          {filterMenu}
        </>
      ),
      replaceHeading: searchVisible ? (
        <WorkSearchField
          ref={searchRef}
          query={query}
          matchCount={recentItems.length}
          onClear={() => {
            setQuery("");
            searchRef.current?.focus();
          }}
          onClose={closeSearch}
        />
      ) : undefined,
      body: renderRecent(),
    },
    spaces: {
      count: starredSpaces.length,
      actions: (
        <>
          <IconAction label="New space…" onClick={() => setCreateOpen(true)}>
            <PlusIcon size={14} />
          </IconAction>
          <IconAction label="Browse spaces" onClick={navigateToSpaces}>
            <ListMagnifyingGlassIcon size={14} />
          </IconAction>
        </>
      ),
      body: spacesBody,
    },
  };

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
      <div ref={columnRef} className="flex h-full min-h-0 flex-col">
        <ChromeBar>
          <h2 className="font-bold text-base">Work</h2>
        </ChromeBar>
        <AutocompleteList className="sidebar-autocomplete-tree !max-h-none !px-2 !pt-2 !pb-2 flex min-h-0 flex-1 flex-col overflow-hidden">
          <div
            ref={sectionsRef}
            className="relative flex min-h-0 flex-1 flex-col overflow-hidden"
          >
            {layoutSections.map((section, index) => {
              const content = sectionContent[section.id];
              const previous = index > 0 ? layoutSections[index - 1] : null;
              const resizable = previous?.open && section.open;
              return (
                <WorkSection
                  key={section.id}
                  label={SECTIONS[section.id].label}
                  open={section.open}
                  count={content.count}
                  onToggle={() => toggleSection(SECTIONS[section.id].key)}
                  actions={content.actions}
                  replaceHeading={content.replaceHeading}
                  height={layout.heights[section.id]}
                  animate={layout.measured && layout.dragging === null}
                  divider={index > 0}
                  resizer={
                    resizable && previous
                      ? layout.resizer(previous.id, section.id)
                      : undefined
                  }
                  resizing={layout.dragging === section.id}
                  contentRef={layout.measureRefs[section.id]}
                >
                  {content.body}
                </WorkSection>
              );
            })}
            <MarqueeOverlay rect={marquee} />
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
