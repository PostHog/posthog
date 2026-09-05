import { MagnifyingGlass } from "@phosphor-icons/react";
import {
  ANY_SOURCE,
  type ChannelItemFilters,
  type ChannelItemGrouping,
  type ChannelItemModel,
  channelItemSortEvent,
  channelItemSources,
  DEFAULT_CHANNEL_ITEM_FILTERS,
  filterChannelItems,
  groupChannelItems,
  hasActiveChannelItemFilters,
  PINNED_SECTION_KEY,
  sortChannelItems,
} from "@posthog/core/canvas/channelItems";
import { getCanvasCellId } from "@posthog/core/command-center/grid";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  InputGroup,
  InputGroupAddon,
  InputGroupInput,
  MenuLabel,
  Skeleton,
  SkeletonText,
} from "@posthog/quill";
import {
  ANALYTICS_EVENTS,
  type TaskListSurface,
} from "@posthog/shared/analytics-events";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
import { ChannelFilterMenu } from "@posthog/ui/features/canvas/components/ChannelFilterMenu";
import { ChannelItemDragPreview } from "@posthog/ui/features/canvas/components/ChannelItemDragPreview";
import type { ChannelItemActions } from "@posthog/ui/features/canvas/components/ChannelItemRow";
import { ChannelItemRow } from "@posthog/ui/features/canvas/components/ChannelItemRow";
import { PinnedRun } from "@posthog/ui/features/canvas/components/PinnedRun";
import { useChannelItemSelection } from "@posthog/ui/features/canvas/hooks/useChannelItemSelection";
import { useLocalDayStart } from "@posthog/ui/features/canvas/hooks/useLocalDayStart";
import { useCommandCenterStore } from "@posthog/ui/features/command-center/commandCenterStore";
import {
  placeCanvasInCommandCenter,
  placeTaskInCommandCenter,
} from "@posthog/ui/features/command-center/placeTaskInCommandCenter";
import { EditListItemAppearanceDialog } from "@posthog/ui/features/sidebar/components/EditListItemAppearanceDialog";
import { MarqueeOverlay } from "@posthog/ui/features/sidebar/components/MarqueeOverlay";
import { SidebarBulkActionBar } from "@posthog/ui/features/sidebar/components/SidebarBulkActionBar";
import { useSidebarStore } from "@posthog/ui/features/sidebar/sidebarStore";
import { taskDragSiblings } from "@posthog/ui/features/sidebar/taskDrag";
import { usePinDrag } from "@posthog/ui/features/sidebar/usePinDrag";
import { useRenameTask } from "@posthog/ui/features/tasks/useTaskMutations";
import { track } from "@posthog/ui/shell/analytics";
import { logger } from "@posthog/ui/shell/logger";
import { motion, useReducedMotion } from "framer-motion";
import {
  Fragment,
  type ReactNode,
  useCallback,
  useMemo,
  useState,
} from "react";

const log = logger.scope("channel-items-pane");

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

const SKELETON_ROW_WIDTHS = [60, 80, 40, 75, 50, 66] as const;

function ChannelItemsSkeleton() {
  return (
    <div aria-hidden className="flex flex-col gap-px">
      {SKELETON_ROW_WIDTHS.map((width) => (
        <div key={width} className="flex items-center gap-2 px-2 py-1.5">
          <Skeleton className="size-4 shrink-0 rounded" />
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

type ListState = "loading" | "empty" | "ready";

function listStateOf({
  isLoading,
  itemCount,
  narrowed,
}: {
  isLoading: boolean;
  itemCount: number;
  narrowed: boolean;
}): ListState {
  if (isLoading && itemCount === 0) return "loading";
  if (itemCount === 0 && !narrowed) return "empty";
  return "ready";
}

export function ChannelItemsPane({
  items,
  isLoading,
  actions,
  activeKey,
  surface,
  headerLeft,
  hasMultipleAuthors = true,
  hasRuns = true,
  cap,
  channelIdFor,
  emptyState,
  overlay,
  searchLabel = "Search sessions",
}: {
  items: readonly ChannelItemModel[];
  isLoading: boolean;
  actions: ChannelItemActions;
  activeKey: string | null;
  surface: TaskListSurface;
  headerLeft?: ReactNode;
  hasMultipleAuthors?: boolean;
  hasRuns?: boolean;
  cap?: number;
  channelIdFor?: (item: ChannelItemModel) => string | undefined;
  emptyState: ReactNode;
  overlay?: ReactNode;
  searchLabel?: string;
}) {
  const [editingTaskId, setEditingTaskId] = useState<string | null>(null);
  const { renameTask } = useRenameTask();
  const commandCenterCells = useCommandCenterStore((state) => state.cells);
  const [query, setQuery] = useState("");
  const [appearanceOpen, setAppearanceOpen] = useState(false);

  const rawFilters = useSidebarStore((state) => state.channelItemFilters);
  const setFilters = useSidebarStore((state) => state.setChannelItemFilters);
  const sort = useSidebarStore((state) => state.channelItemSort);
  const setSort = useSidebarStore((state) => state.setChannelItemSort);
  const rawGrouping = useSidebarStore((state) => state.channelItemGrouping);
  const setGrouping = useSidebarStore((state) => state.setChannelItemGrouping);
  const grouping = hasRuns ? rawGrouping : "date";

  const client = useOptionalAuthenticatedClient();
  const { data: currentUser } = useCurrentUser({ client });
  const meUuid = currentUser?.uuid ?? null;
  const me = useMemo(() => ({ uuid: meUuid }), [meUuid]);

  const changeGrouping = (next: ChannelItemGrouping) => {
    if (next === grouping) return;
    setGrouping(next);
    track(ANALYTICS_EVENTS.TASK_LIST_GROUPING_CHANGED, {
      group_by: next,
      sort_by: channelItemSortEvent(sort),
      surface,
    });
  };

  const sources = useMemo(() => channelItemSources(items), [items]);
  const filters = useMemo<ChannelItemFilters>(() => {
    const sourceMissing =
      rawFilters.source !== ANY_SOURCE && !sources.includes(rawFilters.source);
    const scoped: ChannelItemFilters = {
      ...rawFilters,
      ...(hasMultipleAuthors ? {} : { createdBy: "anyone" as const }),
      ...(sourceMissing ? { source: ANY_SOURCE } : {}),
    };
    return hasRuns
      ? scoped
      : { ...scoped, attention: "any", environment: "any", source: ANY_SOURCE };
  }, [rawFilters, hasMultipleAuthors, hasRuns, sources]);
  const filtersActive = hasActiveChannelItemFilters(filters);

  const listItems = useMemo(() => {
    const ordered = sortChannelItems(
      filterChannelItems(items, { query, filters, me }),
      sort,
    );
    return cap === undefined ? ordered : ordered.slice(0, cap);
  }, [items, query, filters, sort, me, cap]);
  const dayStart = useLocalDayStart();
  const sections = useMemo(
    () => groupChannelItems(listItems, sort, new Date(dayStart), grouping),
    [listItems, sort, dayStart, grouping],
  );

  const pinnedItems =
    sections.find((section) => section.key === PINNED_SECTION_KEY)?.items ?? [];
  const datedSections = sections.filter(
    (section) => section.key !== PINNED_SECTION_KEY,
  );
  const showPinnedBadges = datedSections[0]?.label == null;

  const narrowed = filtersActive || query.trim().length > 0;
  const listState = listStateOf({
    isLoading,
    itemCount: items.length,
    narrowed,
  });

  const {
    selectedTaskIds,
    clearSelection,
    bulkActions,
    archiveConfirm,
    marquee,
    listAnchorRef,
    onRowClick,
  } = useChannelItemSelection({ listItems, activeKey, open: actions.open });

  const prefersReducedMotion = useReducedMotion();
  const dragSiblingsFor = useCallback(
    (item: ChannelItemModel) =>
      item.kind === "task"
        ? taskDragSiblings(item.id, listItems, (candidate) =>
            candidate.kind === "task" ? candidate.id : null,
          )
        : [],
    [listItems],
  );
  const pinDrag = usePinDrag<ChannelItemModel>({
    isPinned: (item) => item.pinned,
    setPinned: actions.setPinned,
    getDragSiblings: dragSiblingsFor,
  });

  const rowTransition = prefersReducedMotion
    ? { duration: 0 }
    : {
        layout: { type: "spring" as const, stiffness: 520, damping: 42 },
        height: { duration: 0.16, ease: "easeOut" as const },
        opacity: { duration: 0.1 },
      };

  const taskRow = (item: ChannelItemModel, showPinBadge: boolean) => {
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
          channelId={channelIdFor?.(item)}
          isActive={item.key === activeKey}
          isSelected={inSelection}
          showPinBadge={showPinBadge}
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
          onClick={(e) => onRowClick(item, e)}
          isEditing={item.kind === "task" && editingTaskId === item.id}
          onRename={
            item.kind === "task" ? () => setEditingTaskId(item.id) : undefined
          }
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

  return (
    <div
      ref={listAnchorRef}
      className="relative flex min-h-0 flex-1 flex-col"
      data-testid="channel-items-pane"
    >
      {/* The header stays through the load: the tabs in `headerLeft` are how you
          choose what the list is fetching, so they can't wait on the fetch. */}
      <div className="flex flex-col gap-1 border-border border-b px-2 py-1.5">
        {headerLeft && (
          <div className="flex flex-wrap items-center gap-0.5">
            {headerLeft}
          </div>
        )}
        <InputGroup className="h-7">
          <InputGroupAddon align="inline-start">
            <MagnifyingGlass size={12} className="text-muted-foreground" />
          </InputGroupAddon>
          <InputGroupInput
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search…"
            aria-label={searchLabel}
            className="text-[12px]"
          />
          <InputGroupAddon align="inline-end">
            <ChannelFilterMenu
              filters={filters}
              onFilterChange={(key, value) =>
                setFilters({ ...rawFilters, [key]: value })
              }
              onClearFilters={() => setFilters(DEFAULT_CHANNEL_ITEM_FILTERS)}
              sort={sort}
              onSortChange={setSort}
              grouping={grouping}
              onGroupingChange={changeGrouping}
              onEditAppearance={() => setAppearanceOpen(true)}
              sources={sources}
              showCreatedBy={hasMultipleAuthors}
              showRunFilters={hasRuns}
              active={filtersActive}
            />
          </InputGroupAddon>
        </InputGroup>
      </div>

      {/* biome-ignore lint/a11y/noStaticElementInteractions: drag-and-drop container */}
      <div
        aria-busy={isLoading}
        className="scroll-mask-4 min-h-0 flex-1 overflow-y-auto px-2 pt-1 pb-2"
        onDragOver={pinDrag.listProps.onDragOver}
        onDrop={pinDrag.listProps.onDrop}
      >
        {listState === "loading" && <ChannelItemsSkeleton />}
        {listState === "empty" && emptyState}
        {listState === "ready" &&
          (sections.length > 0 ? (
            <div className="flex flex-col gap-px">
              <PinnedRun
                dropRef={pinDrag.pinnedZoneRef}
                dragging={pinDrag.drag !== null}
                highlight={Boolean(
                  pinDrag.drag?.overPinned && !pinDrag.drag.sourcePinned,
                )}
                hasItems={pinnedItems.length > 0}
              >
                {pinnedItems.map((item) => taskRow(item, showPinnedBadges))}
              </PinnedRun>
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
      {overlay}
      <MarqueeOverlay rect={marquee} />

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
          currentUserUuid={currentUser?.uuid}
        />
      ) : null}
      <EditListItemAppearanceDialog
        surface={surface}
        open={appearanceOpen}
        onOpenChange={setAppearanceOpen}
      />
    </div>
  );
}
