import {
  ChatsCircleIcon,
  MagnifyingGlass,
  PackageIcon,
  ShapesIcon,
} from "@phosphor-icons/react";
import {
  ANY_SOURCE,
  type ChannelItemFilters,
  type ChannelItemGrouping,
  type ChannelItemModel,
  type ChannelItemSort,
  channelItemSortEvent,
  channelItemSources,
  DEFAULT_CHANNEL_ITEM_FILTERS,
  DEFAULT_CHANNEL_ITEM_GROUPING,
  DEFAULT_CHANNEL_ITEM_SORT,
  filterChannelItems,
  groupChannelItems,
  hasActiveChannelItemFilters,
  PINNED_SECTION_KEY,
  sortChannelItems,
} from "@posthog/core/canvas/channelItems";
import { getCanvasCellId } from "@posthog/core/command-center/grid";
import {
  Button,
  cn,
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Input,
  MenuLabel,
  Skeleton,
  SkeletonText,
  Tabs,
  TabsList,
  TabsTrigger,
} from "@posthog/quill";
import { LOOPS_FLAG } from "@posthog/shared";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import type { Task } from "@posthog/shared/domain-types";
import { ChannelBackRow } from "@posthog/ui/features/canvas/components/ChannelBackRow";
import { ChannelFilterMenu } from "@posthog/ui/features/canvas/components/ChannelFilterMenu";
import { ChannelItemDragPreview } from "@posthog/ui/features/canvas/components/ChannelItemDragPreview";
import { ChannelItemRow } from "@posthog/ui/features/canvas/components/ChannelItemRow";
import { ChannelsFab } from "@posthog/ui/features/canvas/components/ChannelsFab";
import { cnHeaderButton } from "@posthog/ui/features/canvas/components/channelHeaderButton";
import {
  type ChannelPageKey,
  channelPageLabel,
} from "@posthog/ui/features/canvas/components/channelPages";
import { useChannelItems } from "@posthog/ui/features/canvas/hooks/useChannelItems";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useChannelTasksRunState } from "@posthog/ui/features/canvas/hooks/useChannelTasksRunState";
import { useLocalDayStart } from "@posthog/ui/features/canvas/hooks/useLocalDayStart";
import { SHORTCUTS } from "@posthog/ui/features/command/keyboard-shortcuts";
import { useCommandCenterStore } from "@posthog/ui/features/command-center/commandCenterStore";
import {
  placeCanvasInCommandCenter,
  placeTaskInCommandCenter,
} from "@posthog/ui/features/command-center/placeTaskInCommandCenter";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { EditListItemAppearanceDialog } from "@posthog/ui/features/sidebar/components/EditListItemAppearanceDialog";
import { SidebarKbdHint } from "@posthog/ui/features/sidebar/components/items/SidebarKbdHint";
import { MarqueeOverlay } from "@posthog/ui/features/sidebar/components/MarqueeOverlay";
import { SidebarBulkActionBar } from "@posthog/ui/features/sidebar/components/SidebarBulkActionBar";
import { SidebarItem } from "@posthog/ui/features/sidebar/components/SidebarItem";
import { taskDragSiblings } from "@posthog/ui/features/sidebar/taskDrag";
import { useTaskSelectionStore } from "@posthog/ui/features/sidebar/taskSelectionStore";
import { useBulkArchiveConfirm } from "@posthog/ui/features/sidebar/useBulkArchiveConfirm";
import { useClearSelectionOnEscape } from "@posthog/ui/features/sidebar/useClearSelectionOnEscape";
import { useMarqueeSelection } from "@posthog/ui/features/sidebar/useMarqueeSelection";
import { usePinDrag } from "@posthog/ui/features/sidebar/usePinDrag";
import { useSidebarBulkActions } from "@posthog/ui/features/sidebar/useSidebarBulkActions";
import { useRenameTask } from "@posthog/ui/features/tasks/useTaskMutations";
import { track } from "@posthog/ui/shell/analytics";
import { logger } from "@posthog/ui/shell/logger";
import { useNavigate, useRouterState } from "@tanstack/react-router";
import { motion, useReducedMotion } from "framer-motion";
import {
  Fragment,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

const RECENTS_CAP = 30;
const log = logger.scope("channel-sidebar");

function commandCenterAssigner(item: ChannelItemModel): () => void {
  return () => {
    if (item.kind === "canvas") {
      placeCanvasInCommandCenter(item.id, item.title);
    } else {
      placeTaskInCommandCenter(item.id, item.title);
    }
  };
}

function isInCommandCenter(
  item: ChannelItemModel,
  commandCenterCells: readonly (string | null)[],
): boolean {
  return commandCenterCells.some((cell) =>
    item.kind === "canvas"
      ? getCanvasCellId(cell) === item.id
      : cell === item.id,
  );
}

/** The list holds two kinds of thing, and shows one of them at a time. */
type ChannelTab = ChannelItemModel["kind"];

const CHANNEL_TABS: readonly {
  value: ChannelTab;
  label: string;
}[] = [
  { value: "task", label: "Sessions" },
  { value: "canvas", label: "Canvases" },
];

function RecentSectionHeader({
  tab,
  tabs,
  onTabChange,
  searchOpen,
  onToggleSearch,
  query,
  onQueryChange,
  filters,
  onFilterChange,
  onClearFilters,
  sort,
  onSortChange,
  grouping,
  onGroupingChange,
  onEditAppearance,
  sources,
  showCreatedBy,
  showRunFilters,
  filtersActive,
}: {
  tab: ChannelTab;
  tabs: readonly { value: ChannelTab; label: string }[];
  onTabChange: (tab: ChannelTab) => void;
  searchOpen: boolean;
  onToggleSearch: () => void;
  query: string;
  onQueryChange: (value: string) => void;
  filters: ChannelItemFilters;
  onFilterChange: <K extends keyof ChannelItemFilters>(
    key: K,
    value: ChannelItemFilters[K],
  ) => void;
  onClearFilters: () => void;
  sort: ChannelItemSort;
  onSortChange: (sort: ChannelItemSort) => void;
  grouping: ChannelItemGrouping;
  onGroupingChange: (grouping: ChannelItemGrouping) => void;
  onEditAppearance: () => void;
  sources: readonly string[];
  /** False in #me, where every session is yours and the filter says nothing. */
  showCreatedBy: boolean;
  /** False on the canvases tab: a canvas has no run to ask these about. */
  showRunFilters: boolean;
  filtersActive: boolean;
}) {
  return (
    <>
      <div className="flex flex-wrap items-center gap-0.5">
        {/* The tabs name the list, so it has no label of its own. Controls
            wrap under the tabs when the sidebar is narrow, so tab labels are
            never cut off. */}
        <Tabs
          value={tab}
          onValueChange={(value: string) => onTabChange(value as ChannelTab)}
          className="shrink-0"
        >
          {/* text-[13px] is the sidebar's own scale: quill's default tab is
              sized for a page header, which reads as a heading over this list. */}
          {/* quill-tabs-fill: the active/hover fills, from globals.css — they
              can't be utilities here, see the rule's comment. */}
          <TabsList
            variant="line"
            className="quill-tabs-fill h-auto gap-0.5 border-b-0"
          >
            {tabs.map(({ value, label }) => (
              <TabsTrigger
                key={value}
                value={value}
                className="shrink-0 rounded-sm px-1 py-0.5 text-[13px]"
              >
                <span className="whitespace-nowrap">{label}</span>
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
        <div className="ml-auto flex items-center gap-0.5">
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
            onFilterChange={onFilterChange}
            onClearFilters={onClearFilters}
            sort={sort}
            onSortChange={onSortChange}
            grouping={grouping}
            onGroupingChange={onGroupingChange}
            onEditAppearance={onEditAppearance}
            sources={sources}
            showCreatedBy={showCreatedBy}
            showRunFilters={showRunFilters}
            active={filtersActive}
          />
        </div>
      </div>
      {searchOpen && (
        <div className="px-1 pb-1">
          <Input
            autoFocus
            value={query}
            onChange={(event) => onQueryChange(event.target.value)}
            placeholder="Search…"
            aria-label={
              tab === "canvas" ? "Search canvases" : "Search sessions"
            }
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
      {/* Stands in for the tabs row, so it carries that row's scale. */}
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

/** An empty tab says what would fill it, rather than what the space holds. */
function TabEmptyState({ tab }: { tab: ChannelTab }) {
  return (
    <Empty className="border-0 py-6">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          {tab === "canvas" ? (
            <ShapesIcon size={18} />
          ) : (
            <ChatsCircleIcon size={18} />
          )}
        </EmptyMedia>
        <EmptyTitle>
          {tab === "canvas" ? "No canvases yet" : "No sessions yet"}
        </EmptyTitle>
        <EmptyDescription>
          {tab === "canvas"
            ? "Canvases you create in this space show up here."
            : "Sessions you start in this space show up here."}
        </EmptyDescription>
      </EmptyHeader>
    </Empty>
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

  // A space opens on its sessions. The pane stays mounted across a space
  // switch, so the tab is stored against the space it was chosen in rather than
  // carried into the next one; the filters below deliberately do carry over.
  const [chosenTab, setChosenTab] = useState({
    channelId,
    tab: "task" as ChannelTab,
  });
  const tab = chosenTab.channelId === channelId ? chosenTab.tab : "task";
  const setTab = (next: ChannelTab) => setChosenTab({ channelId, tab: next });
  const [searchOpen, setSearchOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [rawFilters, setFilters] = useState<ChannelItemFilters>(
    DEFAULT_CHANNEL_ITEM_FILTERS,
  );
  const [sort, setSort] = useState<ChannelItemSort>(DEFAULT_CHANNEL_ITEM_SORT);
  const [rawGrouping, setGrouping] = useState<ChannelItemGrouping>(
    DEFAULT_CHANNEL_ITEM_GROUPING,
  );
  // Canvases carry no repository, so grouping by one would file the whole tab
  // under a single heading. Neutralised as well as hidden, the way the run
  // filters above are.
  const grouping = tab === "canvas" ? "date" : rawGrouping;
  const [appearanceOpen, setAppearanceOpen] = useState(false);
  const changeGrouping = (next: ChannelItemGrouping) => {
    if (next === grouping) return;
    setGrouping(next);
    track(ANALYTICS_EVENTS.TASK_LIST_GROUPING_CHANGED, {
      group_by: next,
      sort_by: channelItemSortEvent(sort),
      surface: "space",
    });
  };
  // Every session in #me is yours, so the author filter has nothing to sort by.
  // The state survives a space switch, so the value is neutralised here as well
  // as hidden — otherwise "Other people" carried in from a shared space would
  // empty this list with no visible control to undo it.
  const { channels } = useChannels();
  // By type, not by name: the list relabels the personal channel on the way in,
  // so its name is no longer the backend's.
  const channel = channels.find((c) => c.id === channelId);
  const isPersonalChannel = channel?.channelType === "personal";
  const visibleTabs = CHANNEL_TABS;
  // The tab is the list, so everything below it — the filters, the empty state,
  // the sections — is about one kind of thing at a time.
  const tabItems = useMemo(
    () => items.filter((item) => item.kind === tab),
    [items, tab],
  );
  // The menu only offers sources the list holds, so it is built from everything
  // in the tab rather than from what the current filters left behind — picking
  // one source must not be what removes the others from the menu.
  const sources = useMemo(() => channelItemSources(tabItems), [tabItems]);
  // A canvas has no run, so the three run filters can only ever empty the
  // canvases tab. Same treatment as createdBy above: neutralised as well as
  // hidden, or a choice made on the sessions tab would empty this one.
  //
  // A source the tab has none of goes the same way, and for the same reason: it
  // would empty the list while its submenu shows no chosen option, so there'd be
  // nothing to switch off. Rows arriving later put the source back, because the
  // stored filter is untouched.
  const filters = useMemo<ChannelItemFilters>(() => {
    const sourceMissing =
      rawFilters.source !== ANY_SOURCE && !sources.includes(rawFilters.source);
    const scoped =
      isPersonalChannel || sourceMissing
        ? {
            ...rawFilters,
            ...(isPersonalChannel ? { createdBy: "anyone" as const } : {}),
            ...(sourceMissing ? { source: ANY_SOURCE } : {}),
          }
        : rawFilters;
    return tab === "canvas"
      ? {
          ...scoped,
          attention: "any",
          environment: "any",
          source: ANY_SOURCE,
        }
      : scoped;
  }, [isPersonalChannel, rawFilters, sources, tab]);
  const filtersActive = hasActiveChannelItemFilters(filters);

  const base = `/spaces/${channelId}`;
  // Activeness is a key comparison rather than a flag baked into each item, so
  // navigating doesn't rebuild the list.
  const activeKey = useMemo(() => {
    const dashboard = pathname.match(/\/dashboards\/([^/]+)$/);
    if (dashboard) return `canvas:${dashboard[1]}`;
    const task = pathname.match(/\/tasks\/([^/]+)$/);
    return task ? `task:${task[1]}` : null;
  }, [pathname]);

  // Pins sort to the top because a pin is a request not to lose the thing:
  // below the chosen order it would fall off the end of the cap. The cap is
  // applied to the flat list, before the sections, so the number of rows a
  // reader gets doesn't depend on how many days they span.
  const recentItems = useMemo(
    () =>
      sortChannelItems(
        filterChannelItems(tabItems, { query, filters, me }),
        sort,
      ).slice(0, RECENTS_CAP),
    [tabItems, query, filters, sort, me],
  );
  // Dated against the day rather than the moment, so the headers follow local
  // midnight even when the list itself hasn't changed for hours.
  const dayStart = useLocalDayStart();
  const sections = useMemo(
    () => groupChannelItems(recentItems, sort, new Date(dayStart), grouping),
    [recentItems, sort, dayStart, grouping],
  );

  const pinnedSection = sections.find(
    (section) => section.key === PINNED_SECTION_KEY,
  );
  const datedSections = sections.filter(
    (section) => section.key !== PINNED_SECTION_KEY,
  );
  // Under "Pinned" every row wears the same badge, so the header says it once
  // instead, but only while a header below marks where the pins stop. An
  // alphabetical run carries no header, so there the badges stay.
  const showPinnedBadges = datedSections[0]?.label == null;

  const narrowed = filtersActive || searchOpen;
  const listState = listStateOf({
    channelMissing,
    isLoading,
    itemCount: tabItems.length,
    narrowed,
  });
  // The header stays while the list is narrowed, so you can undo whatever
  // emptied it — and while a tab is empty, so you can leave that tab.
  const showHeader = listState === "ready" || listState === "empty";

  // Only sessions take part in a bulk selection: a canvas can't be archived,
  // filed, or tiled the way a session can, so modifier-clicking one just opens it.
  const selectableTaskIds = useMemo(
    () => recentItems.filter((i) => i.kind === "task").map((i) => i.id),
    [recentItems],
  );
  const selectedTaskIds = useTaskSelectionStore((s) => s.selectedTaskIds);
  const toggleTaskSelection = useTaskSelectionStore(
    (s) => s.toggleTaskSelection,
  );
  const selectRange = useTaskSelectionStore((s) => s.selectRange);
  const clearSelection = useTaskSelectionStore((s) => s.clearSelection);
  const pruneSelection = useTaskSelectionStore((s) => s.pruneSelection);
  useClearSelectionOnEscape();
  const listAnchorRef = useRef<HTMLDivElement | null>(null);
  const marquee = useMarqueeSelection(listAnchorRef);
  const prefersReducedMotion = useReducedMotion();
  // A drag that starts on a selected row carries the whole selection, so a pin
  // or an unpin applies to every row the user picked, not just the grabbed one.
  const dragSiblingsFor = useCallback(
    (item: ChannelItemModel) =>
      item.kind === "task"
        ? taskDragSiblings(item.id, recentItems, (candidate) =>
            candidate.kind === "task" ? candidate.id : null,
          )
        : [],
    [recentItems],
  );
  const pinDrag = usePinDrag<ChannelItemModel>({
    isPinned: (item) => item.pinned,
    setPinned: actions.setPinned,
    getDragSiblings: dragSiblingsFor,
  });

  useEffect(() => {
    pruneSelection(selectableTaskIds);
  }, [selectableTaskIds, pruneSelection]);

  // A bulk action acts on exactly the rows that are highlighted. The open
  // session used to be folded in as well, which told you "2 selected" after one
  // cmd-click and archived a session you never picked.
  const activeTaskId = activeKey?.startsWith("task:")
    ? activeKey.slice("task:".length)
    : null;

  const selectedTasks = useMemo(() => {
    const selected = new Set(selectedTaskIds);
    return recentItems
      .filter(
        (i): i is ChannelItemModel & { task: Task } =>
          i.kind === "task" && i.task !== null && selected.has(i.id),
      )
      .map((i) => i.task);
  }, [recentItems, selectedTaskIds]);
  const selectedTasksRunState = useChannelTasksRunState(selectedTasks);
  const bulkActions = useSidebarBulkActions(
    selectedTaskIds,
    selectedTasksRunState,
  );
  const archiveConfirm = useBulkArchiveConfirm(bulkActions);

  const handleRowClick = (item: ChannelItemModel, e: React.MouseEvent) => {
    if (item.kind !== "task") {
      actions.open(item);
      return;
    }
    if (e.shiftKey) {
      e.preventDefault();
      selectRange(item.id, selectableTaskIds, activeTaskId);
      return;
    }
    if (e.metaKey || e.ctrlKey) {
      e.preventDefault();
      toggleTaskSelection(item.id);
      return;
    }
    clearSelection();
    actions.open(item);
  };

  const rowTransition = prefersReducedMotion
    ? { duration: 0 }
    : {
        layout: { type: "spring" as const, stiffness: 520, damping: 42 },
        height: { duration: 0.16, ease: "easeOut" as const },
        opacity: { duration: 0.1 },
      };

  /**
   * The pinned run, doubling as the box that decides pin from unpin. Always
   * rendered, empty or not, and it opens on a drag rather than appearing. See
   * below for why nothing here may jump into place.
   */
  const pinnedRun = () => {
    const drag = pinDrag.drag;
    const pinnedItems = pinnedSection?.items ?? [];
    return (
      <div
        key={PINNED_SECTION_KEY}
        ref={pinDrag.pinnedZoneRef}
        className={cn(
          // `min-h-0` is the resting end of the transition. min-height starts at
          // `auto`, which is not interpolable, so without it the run snaps open.
          "flex min-h-0 flex-col gap-px rounded-md transition-[min-height,background-color] duration-150 ease-out motion-reduce:transition-none",
          // A floor, not a height, so a taller run keeps its own.
          drag && "min-h-[100px]",
          drag?.overPinned &&
            !drag.sourcePinned &&
            "bg-accent-2 ring-1 ring-accent-6",
        )}
      >
        {/* Opened by a transition rather than by appearing: a drag dies at
            birth if anything above its source jumps in the same frame as
            `dragstart`. Grid rows, so the label keeps its own height. */}
        <div
          className={cn(
            "grid transition-[grid-template-rows] duration-150 ease-out motion-reduce:transition-none",
            pinnedItems.length > 0 || drag
              ? "grid-rows-[1fr]"
              : "grid-rows-[0fr]",
          )}
        >
          <div className="overflow-hidden">
            <MenuLabel>Pinned</MenuLabel>
          </div>
        </div>
        {pinnedItems.map((item) => taskRow(item, showPinnedBadges))}
      </div>
    );
  };

  // Every row gets the wrapper, not just the dragged one. Swapping a row
  // between wrapped and bare remounts it, and Chromium ends a native drag the
  // moment its source leaves the DOM.
  const taskRow = (item: (typeof items)[number], showPinBadge: boolean) => {
    const inSelection =
      item.kind === "task" && selectedTaskIds.includes(item.id);
    return (
      <motion.div
        key={item.key}
        initial={false}
        animate={
          pinDrag.drag?.items.some((dragged) => dragged.key === item.key)
            ? { height: 0, opacity: 0 }
            : { height: "auto", opacity: 1 }
        }
        transition={rowTransition}
        className="overflow-hidden"
      >
        <ChannelItemRow
          item={item}
          channelId={channelId}
          isActive={item.key === activeKey}
          isSelected={inSelection}
          showPinBadge={showPinBadge}
          // Right-clicking inside a selection acts on the selection; right-clicking
          // outside it drops the selection first, so the menu that opens is about
          // the row under the pointer and nothing else.
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
          actions={actions}
          onClick={(e) => handleRowClick(item, e)}
          isEditing={item.kind === "task" && editingTaskId === item.id}
          onRename={
            item.kind === "task" ? () => setEditingTaskId(item.id) : undefined
          }
          // Undefined disables the menu item when this item is already present;
          // duplicating the same task or canvas would make the grid ambiguous.
          onAddToCommandCenter={
            !isInCommandCenter(item, commandCenterCells)
              ? commandCenterAssigner(item)
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
          onDragStart={
            item.kind === "task"
              ? (event) => pinDrag.onItemDragStart(item, event)
              : undefined
          }
          onDragEnd={item.kind === "task" ? pinDrag.onItemDragEnd : undefined}
        />
      </motion.div>
    );
  };

  // Label comes from the shared space-page table, so a sidebar row and the
  // header breadcrumb for the same page can never disagree. No icon: this is a
  // short list of words, and glyphs here only compete with the status dots
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
    <div className="flex h-full min-h-0 flex-col">
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
              to: "/spaces/$channelId/new",
              params: { channelId },
            })
          }
          // ⌘N inside a space lands on this same route (openTaskInput scopes to
          // the channel you're in), so the row can claim the key.
          endHint={<SidebarKbdHint keys={SHORTCUTS.NEW_TASK} />}
        />
        {sectionRow(
          "home",
          base,
          () =>
            void navigate({ to: "/spaces/$channelId", params: { channelId } }),
        )}
        {sectionRow(
          "context",
          `${base}/context`,
          () =>
            void navigate({
              to: "/spaces/$channelId/context",
              params: { channelId },
            }),
        )}
        {loopsEnabled &&
          sectionRow(
            "loops",
            `${base}/loops`,
            () =>
              void navigate({
                to: "/spaces/$channelId/loops",
                params: { channelId },
              }),
          )}
      </div>

      {/* Relative so the FAB and the drag-selection band can float over the
          list. The tabs sit above the scroll container rather than in it: they
          are how you leave whatever the list is showing, so they can't scroll
          away with it. */}
      <div
        ref={listAnchorRef}
        className="relative mt-2 flex min-h-0 flex-1 flex-col"
      >
        {showHeader && (
          <div className="border-border border-b px-2">
            <RecentSectionHeader
              tab={tab}
              tabs={visibleTabs}
              onTabChange={setTab}
              searchOpen={searchOpen}
              onToggleSearch={() => {
                if (searchOpen) setQuery("");
                setSearchOpen(!searchOpen);
              }}
              query={query}
              onQueryChange={setQuery}
              filters={filters}
              // Written against the stored filters, not the narrowed ones the
              // menu displays: a choice made under one tab has to survive a
              // write made under another.
              onFilterChange={(key, value) =>
                setFilters((prev) => ({ ...prev, [key]: value }))
              }
              onClearFilters={() => setFilters(DEFAULT_CHANNEL_ITEM_FILTERS)}
              sort={sort}
              onSortChange={setSort}
              grouping={grouping}
              onGroupingChange={changeGrouping}
              onEditAppearance={() => setAppearanceOpen(true)}
              sources={sources}
              showCreatedBy={!isPersonalChannel}
              showRunFilters={tab === "task"}
              filtersActive={filtersActive}
            />
          </div>
        )}
        {/* Pin and unpin stay reachable from the row's menu and its context
            menu, so the drag adds no keyboard-only path. */}

        {/* biome-ignore lint/a11y/noStaticElementInteractions: drag-and-drop container */}
        <div
          aria-busy={isLoading}
          className="scroll-mask-4 min-h-0 flex-1 overflow-y-auto px-2 pt-1 pb-2"
          onDragOver={pinDrag.listProps.onDragOver}
          onDrop={pinDrag.listProps.onDrop}
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

          {showHeader &&
            (listState === "empty" ? (
              <TabEmptyState tab={tab} />
            ) : sections.length > 0 ? (
              <div className="flex flex-col gap-px">
                {/* Always mounted, empty or not. Inserting the run on
                    dragstart restructures the list under the dragged row, and
                    Chromium ends the drag on the spot: dragstart, then dragend,
                    before the pointer moves. Growing one already there is
                    fine. */}
                {pinnedRun()}
                {datedSections.map((section) => (
                  <Fragment key={section.key}>
                    {section.label && <MenuLabel>{section.label}</MenuLabel>}
                    {section.items.map((item) => taskRow(item, true))}
                  </Fragment>
                ))}
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
            ))}
        </div>
        <ChannelsFab channelId={channelId} />
        <MarqueeOverlay rect={marquee} />
      </div>

      {/* Below the list rather than floating over it: the bottom rows are where
          a shift-click range usually ends, and the FAB already sits there. */}
      <SidebarBulkActionBar
        actions={bulkActions}
        onClearSelection={clearSelection}
        onArchive={archiveConfirm.requestArchive}
      />
      {archiveConfirm.dialog}

      {pinDrag.drag ? (
        <ChannelItemDragPreview
          drag={pinDrag.drag}
          x={pinDrag.previewX}
          y={pinDrag.previewY}
        />
      ) : null}
      {/* The list owns the dialog, as it owns every other piece of this
          surface's state; the menu only asks for it to open. */}
      <EditListItemAppearanceDialog
        surface="space"
        open={appearanceOpen}
        onOpenChange={setAppearanceOpen}
      />
    </div>
  );
}
