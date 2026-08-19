import {
  ChatsCircleIcon,
  MagnifyingGlass,
  PackageIcon,
  ShapesIcon,
} from "@phosphor-icons/react";
import {
  ANY_SOURCE,
  type ChannelItemFilters,
  type ChannelItemModel,
  type ChannelItemSort,
  channelItemSources,
  DEFAULT_CHANNEL_ITEM_FILTERS,
  DEFAULT_CHANNEL_ITEM_SORT,
  filterChannelItems,
  groupChannelItems,
  hasActiveChannelItemFilters,
  PINNED_SECTION_KEY,
  sortChannelItems,
} from "@posthog/core/canvas/channelItems";
import { computeEffectiveBulkIds } from "@posthog/core/sidebar/selection";
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
  Tabs,
  TabsList,
  TabsTrigger,
} from "@posthog/quill";
import { LOOPS_FLAG } from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
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
import { useChannelTasksRunState } from "@posthog/ui/features/canvas/hooks/useChannelTasksRunState";
import { useLocalDayStart } from "@posthog/ui/features/canvas/hooks/useLocalDayStart";
import { SHORTCUTS } from "@posthog/ui/features/command/keyboard-shortcuts";
import { useCommandCenterStore } from "@posthog/ui/features/command-center/commandCenterStore";
import { placeTaskInCommandCenter } from "@posthog/ui/features/command-center/placeTaskInCommandCenter";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { SidebarKbdHint } from "@posthog/ui/features/sidebar/components/items/SidebarKbdHint";
import { MarqueeOverlay } from "@posthog/ui/features/sidebar/components/MarqueeOverlay";
import { SidebarBulkActionFooter } from "@posthog/ui/features/sidebar/components/SidebarBulkActionFooter";
import { SidebarItem } from "@posthog/ui/features/sidebar/components/SidebarItem";
import { useTaskSelectionStore } from "@posthog/ui/features/sidebar/taskSelectionStore";
import { useClearSelectionOnEscape } from "@posthog/ui/features/sidebar/useClearSelectionOnEscape";
import { useMarqueeSelection } from "@posthog/ui/features/sidebar/useMarqueeSelection";
import { useSidebarBulkActions } from "@posthog/ui/features/sidebar/useSidebarBulkActions";
import { useRenameTask } from "@posthog/ui/features/tasks/useTaskMutations";
import { logger } from "@posthog/ui/shell/logger";
import { useNavigate, useRouterState } from "@tanstack/react-router";
import { Fragment, useEffect, useMemo, useRef, useState } from "react";

const RECENTS_CAP = 30;
const log = logger.scope("channel-sidebar");

/** The list holds two kinds of thing, and shows one of them at a time. */
type ChannelTab = ChannelItemModel["kind"];

const CHANNEL_TABS: readonly { value: ChannelTab; label: string }[] = [
  { value: "task", label: "Sessions" },
  { value: "canvas", label: "Canvases" },
];

function RecentSectionHeader({
  tab,
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
  sources,
  showCreatedBy,
  showRunFilters,
  filtersActive,
}: {
  tab: ChannelTab;
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
  sources: readonly string[];
  /** False in #me, where every session is yours and the filter says nothing. */
  showCreatedBy: boolean;
  /** False on the canvases tab: a canvas has no run to ask these about. */
  showRunFilters: boolean;
  filtersActive: boolean;
}) {
  return (
    <>
      <div className="flex items-center gap-0.5">
        {/* The tabs name the list, so it has no label of its own. */}
        <Tabs
          value={tab}
          onValueChange={(value: string) => onTabChange(value as ChannelTab)}
          className="min-w-0 flex-1"
        >
          {/* text-[13px] is the sidebar's own scale: quill's default tab is
              sized for a page header, which reads as a heading over this list. */}
          {/* quill-tabs-fill: the active/hover fills, from globals.css — they
              can't be utilities here, see the rule's comment. */}
          <TabsList
            variant="line"
            className="quill-tabs-fill h-auto gap-0.5 border-b-0"
          >
            {CHANNEL_TABS.map(({ value, label }) => (
              <TabsTrigger
                key={value}
                value={value}
                className="rounded-sm px-1 py-0.5 text-[13px]"
              >
                {label}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
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
          sources={sources}
          showCreatedBy={showCreatedBy}
          showRunFilters={showRunFilters}
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
  // Every session in #me is yours, so the author filter has nothing to sort by.
  // The state survives a space switch, so the value is neutralised here as well
  // as hidden — otherwise "Other people" carried in from a shared space would
  // empty this list with no visible control to undo it.
  const { channels } = useChannels();
  // By type, not by name: the list relabels the personal channel on the way in,
  // so its name is no longer the backend's.
  const isPersonalChannel =
    channels.find((c) => c.id === channelId)?.channelType === "personal";
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

  const base = `/website/${channelId}`;
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
    () => groupChannelItems(recentItems, sort, new Date(dayStart)),
    [recentItems, sort, dayStart],
  );

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

  useEffect(() => {
    pruneSelection(selectableTaskIds);
  }, [selectableTaskIds, pruneSelection]);

  // The open session counts as selected, the same way it does in the code
  // sidebar — a bulk action is expected to include what you're looking at. Only
  // a task-kind active row folds in; a canvas can't join a session selection.
  const activeTaskId = activeKey?.startsWith("task:")
    ? activeKey.slice("task:".length)
    : null;
  const effectiveBulkIds = useMemo(
    () => computeEffectiveBulkIds(selectedTaskIds, activeTaskId),
    [selectedTaskIds, activeTaskId],
  );

  const selectedTasks = useMemo(() => {
    const selected = new Set(effectiveBulkIds);
    return recentItems
      .filter(
        (i): i is ChannelItemModel & { task: Task } =>
          i.kind === "task" && i.task !== null && selected.has(i.id),
      )
      .map((i) => i.task);
  }, [recentItems, effectiveBulkIds]);
  const selectedTasksRunState = useChannelTasksRunState(selectedTasks);
  const bulkActions = useSidebarBulkActions(
    effectiveBulkIds,
    selectedTasksRunState,
  );

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

  const commandCenterAssigner = (taskId: string, taskTitle: string) => () =>
    placeTaskInCommandCenter(taskId, taskTitle);

  const taskRow = (item: (typeof items)[number], showPinBadge: boolean) => (
    <ChannelItemRow
      key={item.key}
      item={item}
      channelId={channelId}
      isActive={item.key === activeKey}
      isSelected={item.kind === "task" && effectiveBulkIds.includes(item.id)}
      showPinBadge={showPinBadge}
      actions={actions}
      onClick={(e) => handleRowClick(item, e)}
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
          // ⌘N inside a space lands on this same route (openTaskInput scopes to
          // the channel you're in), so the row can claim the key.
          endHint={<SidebarKbdHint keys={SHORTCUTS.NEW_TASK} />}
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
              sources={sources}
              showCreatedBy={!isPersonalChannel}
              showRunFilters={tab === "task"}
              filtersActive={filtersActive}
            />
          </div>
        )}
        <div
          aria-busy={isLoading}
          className="scroll-mask-4 min-h-0 flex-1 overflow-y-auto px-2 pt-1 pb-2"
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
                {sections.map((section, index) => {
                  // Under "Pinned" every row would wear the same badge, so the
                  // header says it once instead — but only while a header below
                  // marks where the pins stop. An alphabetical run carries no
                  // header of its own, so there the badges stay.
                  const nextRunIsHeaded =
                    sections[index + 1] == null ||
                    sections[index + 1].label != null;
                  const showPinBadge =
                    section.key !== PINNED_SECTION_KEY || !nextRunIsHeaded;
                  return (
                    <Fragment key={section.key}>
                      {section.label && <MenuLabel>{section.label}</MenuLabel>}
                      {section.items.map((item) => taskRow(item, showPinBadge))}
                    </Fragment>
                  );
                })}
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
      <SidebarBulkActionFooter
        actions={bulkActions}
        onClearSelection={clearSelection}
      />
    </div>
  );
}
