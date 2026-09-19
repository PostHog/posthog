import {
  CaretDownIcon,
  CaretRightIcon,
  CaretUpIcon,
  DotsThreeIcon,
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
import {
  Autocomplete,
  AutocompleteList,
  Button,
  cn,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  MenuLabel,
  Skeleton,
  Tabs,
  TabsList,
  TabsTrigger,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { useArchiveTask } from "@posthog/ui/features/archive/useArchiveTask";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
import { ChannelFilterMenu } from "@posthog/ui/features/canvas/components/ChannelFilterMenu";
import type { ChannelItemActions } from "@posthog/ui/features/canvas/components/ChannelItemRow";
import { CreateChannelModal } from "@posthog/ui/features/canvas/components/CreateChannelModal";
import { channelGlyph } from "@posthog/ui/features/canvas/components/channelGlyph";
import { SidebarSearchHeader } from "@posthog/ui/features/canvas/components/SidebarSearchHeader";
import type { TaskRowMenuProps } from "@posthog/ui/features/canvas/components/TaskRowMenu";
import { WorkItemRow } from "@posthog/ui/features/canvas/components/work/WorkItemRow";
import { WorkRowSurface } from "@posthog/ui/features/canvas/components/work/WorkRowSurface";
import {
  type Channel,
  useChannels,
} from "@posthog/ui/features/canvas/hooks/useChannels";
import { useDashboardMutations } from "@posthog/ui/features/canvas/hooks/useDashboards";
import { useLocalDayStart } from "@posthog/ui/features/canvas/hooks/useLocalDayStart";
import { useRecentWorkItems } from "@posthog/ui/features/canvas/hooks/useRecentWorkItems";
import { useIsChannelUnread } from "@posthog/ui/features/canvas/hooks/useUnreadChannels";
import { useCurrentChannelStore } from "@posthog/ui/features/canvas/stores/currentChannelStore";
import { EditListItemAppearanceDialog } from "@posthog/ui/features/sidebar/components/EditListItemAppearanceDialog";
import { useSidebarStore } from "@posthog/ui/features/sidebar/sidebarStore";
import { usePinnedTasks } from "@posthog/ui/features/sidebar/usePinnedTasks";
import { toast } from "@posthog/ui/primitives/toast";
import {
  navigateToChannel,
  navigateToChannelDashboard,
  navigateToChannelTask,
  navigateToSpaces,
  navigateToTaskDetail,
} from "@posthog/ui/router/navigationBridge";
import { track } from "@posthog/ui/shell/analytics";
import { useRouterState } from "@tanstack/react-router";
import { Fragment, type ReactNode, useMemo, useState } from "react";

const RECENT_COLLAPSED_COUNT = 5;

/**
 * A section's heading. The label's left edge is the line every row beneath it
 * lines up to, so the caret sits at the far end rather than pushing the label
 * in — the same shape the space list's headings take.
 */
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
      {/* The caret rides with the label rather than at the far right: this
          heading carries a control of its own there, and the two collide. */}
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
  active = false,
}: {
  label: string;
  onClick: () => void;
  children: ReactNode;
  active?: boolean;
}) {
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Button
            variant="default"
            size="icon-sm"
            aria-label={label}
            data-selected={active || undefined}
            onClick={onClick}
            className="text-muted-foreground data-selected:bg-fill-selected data-selected:text-foreground"
          >
            {children}
          </Button>
        }
      />
      <TooltipContent side="right">{label}</TooltipContent>
    </Tooltip>
  );
}

/** One space. Same row as a Recent item, so the two lists share a rhythm. */
function SpaceRow({
  channel,
  isActive,
  unread,
}: {
  channel: Channel;
  isActive: boolean;
  unread: boolean;
}) {
  return (
    <WorkRowSurface
      optionValue={channel.id}
      data-selected={isActive || undefined}
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
      {/* A hash on shared spaces, so every name starts a glyph's width in and
          the lock on the personal row lines up with them. */}
      <span className="flex size-3.5 shrink-0 items-center justify-center text-muted-foreground">
        {channelGlyph(channel.name, {
          size: 13,
          space: false,
          personal: channel.channelType === "personal",
          private: channel.channelType === "private",
        })}
      </span>
      <span
        className={cn("min-w-0 flex-1 truncate", unread && "font-semibold")}
      >
        {channel.name}
      </span>
      {unread && !isActive && (
        <span
          role="img"
          aria-label="Unread"
          className="size-1.5 shrink-0 rounded-full bg-primary"
        />
      )}
    </WorkRowSurface>
  );
}

/**
 * The Work column: what you touched recently, then the spaces you starred, in
 * a column that never changes shape. Entering a space or a session does not
 * swap it for another pane; the active row just moves.
 *
 * Like the space list and the activity feed it is one permanently open inline
 * Autocomplete: the search box is the column's only focus holder, and ↑/↓/⏎
 * walk every row it is showing.
 */
export function WorkColumn() {
  const [query, setQuery] = useState("");
  // Two separate things: whether the section is open at all (the caret), and
  // whether it is showing everything or its first few (the count button).
  const [recentOpen, setRecentOpen] = useState(true);
  // Which half of Recent is on screen, the way a space's list switches.
  const [kind, setKind] = useState<ChannelItemModel["kind"]>("task");
  const [appearanceOpen, setAppearanceOpen] = useState(false);
  const [recentExpanded, setRecentExpanded] = useState(false);
  const [spacesExpanded, setSpacesExpanded] = useState(true);
  const [createOpen, setCreateOpen] = useState(false);
  const [_scrollRoot, setScrollRoot] = useState<HTMLDivElement | null>(null);

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
  // The space is only "where you are" while a page of it is on screen.
  const activeChannelId = pathname.startsWith("/spaces/")
    ? currentChannelId
    : null;

  const needle = query.trim().toLowerCase();
  // The same controls, reading the same store, as a space's own session list:
  // a choice made in one list is the choice in the other.
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
  const pinnedKeys = useMemo(
    () =>
      new Set(
        items
          .filter((entry) => entry.item.pinned)
          .map((entry) => entry.item.key),
      ),
    [items],
  );
  const matchingItems = useMemo(() => {
    const ofKind = items
      .filter((entry) => entry.item.kind === kind)
      .map((entry) => entry.item);
    const filtered = filterChannelItems(ofKind, { query, filters, me });
    // Recent crosses every space, and every space's pins at the top of one
    // list is a pile nobody asked for. The Pinned filter still finds them;
    // they just sit under the day they were last touched.
    const unpinned = filtered.map((item) =>
      item.pinned ? { ...item, pinned: false } : item,
    );
    return sortChannelItems(unpinned, sort);
  }, [items, kind, query, filters, me, sort]);
  // The same sections a space's own list draws: the pins, then whatever the
  // Group by choice says — days, or repositories.
  const sections = useMemo(
    () => groupChannelItems(matchingItems, sort, new Date(dayStart), grouping),
    [matchingItems, sort, dayStart, grouping],
  );
  // #me leads, then the starred spaces in the list's own (name) order.
  const starredSpaces = useMemo(() => {
    const starred = [
      ...channels.filter((c) => c.channelType === "personal"),
      ...channels.filter((c) => c.channelType !== "personal" && c.starred),
    ];
    return needle
      ? starred.filter((c) => c.name.toLowerCase().includes(needle))
      : starred;
  }, [channels, needle]);

  const { togglePin } = usePinnedTasks();
  const { archiveTask } = useArchiveTask({ navigateUnscoped: true });
  const { setPinned: setCanvasPinned } = useDashboardMutations();
  const channelByKey = useMemo(
    () => new Map(items.map(({ item, channelId }) => [item.key, channelId])),
    [items],
  );
  const actions = useMemo<ChannelItemActions>(
    () => ({
      open: (item: ChannelItemModel) => {
        const channelId = channelByKey.get(item.key);
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
      togglePin: (item) => {
        const pin =
          item.kind === "canvas"
            ? setCanvasPinned(item.id, !item.pinned)
            : togglePin(item.id);
        pin.catch(() => {
          toast.error("Couldn't update pin");
        });
      },
      setPinned: (batch, pinned) => {
        for (const item of batch) {
          const pin =
            item.kind === "canvas"
              ? setCanvasPinned(item.id, pinned)
              : togglePin(item.id);
          pin.catch(() => {
            toast.error("Couldn't update pin");
          });
        }
      },
      archive: (item) => {
        void archiveTask({ taskId: item.id });
      },
    }),
    [archiveTask, channelByKey, setCanvasPinned, togglePin],
  );

  // A search is the user asking for everything that matches, so it opens the
  // list rather than making them expand it first.
  const showAllRecent = recentExpanded || needle !== "";
  // The cap is on rows, not on sections: a section is cut where the cap falls
  // and the ones past it drop, so a collapsed list reads like the open one.
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
  const optionValues = useMemo(
    () => [
      ...shownItems.map((item) => item.key),
      ...starredSpaces.map((channel) => channel.id),
    ],
    [shownItems, starredSpaces],
  );

  const spaceNameFor = (item: ChannelItemModel): string | undefined => {
    const channelId = channelByKey.get(item.key);
    return channels.find((channel) => channel.id === channelId)?.name;
  };

  const menuFor = (item: ChannelItemModel): TaskRowMenuProps => ({
    kind: item.kind,
    id: item.id,
    title: item.title,
    isPinned: pinnedKeys.has(item.key),
    task: item.task ?? undefined,
    channelId: channelByKey.get(item.key),
    onTogglePin: () => actions.togglePin(item),
    onArchive: item.kind === "task" ? () => actions.archive(item) : undefined,
  });

  return (
    <Autocomplete<string>
      inline
      // Pinned open: this list is the pane itself, and a closed combobox stops
      // answering the arrow keys.
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
        <SidebarSearchHeader
          title="Work"
          query={query}
          placeholder="Search sessions and spaces…"
          searchLabel="Search work"
          onClear={() => setQuery("")}
        />
        <AutocompleteList
          ref={setScrollRoot}
          className="sidebar-autocomplete-tree scroll-mask-8 !max-h-none !px-2 !pt-2 !pb-2 min-h-0 flex-1 scroll-py-8 flex-col gap-px overflow-y-auto"
        >
          <SectionHeading
            label="Recent"
            expanded={recentOpen}
            onToggle={() => setRecentOpen((value) => !value)}
            trailing={null}
          />
          {recentOpen && (
            <div className="flex items-center gap-1 px-1 pt-0.5 pb-1">
              <Tabs
                value={kind}
                onValueChange={(value: string) =>
                  setKind(value as ChannelItemModel["kind"])
                }
                className="min-w-0 flex-1"
              >
                <TabsList
                  variant="line"
                  className="quill-tabs-fill h-auto gap-0.5 border-b-0"
                >
                  <TabsTrigger
                    value="task"
                    className="shrink-0 rounded-sm px-2 py-0.5 text-[12px]"
                  >
                    Sessions
                  </TabsTrigger>
                  <TabsTrigger
                    value="canvas"
                    className="shrink-0 rounded-sm px-2 py-0.5 text-[12px]"
                  >
                    Canvases
                  </TabsTrigger>
                </TabsList>
              </Tabs>
              <ChannelFilterMenu
                filters={filters}
                onFilterChange={(key, value) =>
                  setFilters({ ...filters, [key]: value })
                }
                onClearFilters={() => setFilters(DEFAULT_CHANNEL_ITEM_FILTERS)}
                sort={sort}
                onSortChange={setSort}
                grouping={grouping}
                onGroupingChange={setGrouping}
                onEditAppearance={() => setAppearanceOpen(true)}
                sources={sources}
                showCreatedBy
                showRunFilters={kind === "task"}
                active={hasActiveChannelItemFilters(filters)}
              />
            </div>
          )}
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
                  : kind === "canvas"
                    ? "Canvases you open show up here."
                    : "Sessions you open show up here."}
              </p>
            ) : (
              <div className="flex flex-col gap-px">
                {shownSections.map((section, index) => (
                  <Fragment key={section.key}>
                    {section.label && (
                      // A day sits at the rows' own left edge, so the list has
                      // one margin rather than two. A hairline above it is
                      // what separates the groups; the label itself stays
                      // sentence case, which is what keeps it from reading as
                      // another section heading.
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
                    {section.items.map((item) => (
                      <WorkItemRow
                        key={item.key}
                        item={item}
                        isActive={item.key === activeKey}
                        onOpen={() => actions.open(item)}
                        menu={menuFor(item)}
                        spaceName={spaceNameFor(item)}
                      />
                    ))}
                  </Fragment>
                ))}
              </div>
            ))}
          {recentOpen && canExpandRecent && (
            <button
              type="button"
              aria-expanded={recentExpanded}
              className="group/expand mt-0.5 flex h-6 w-full items-center justify-center gap-1 rounded-md text-[11px] text-muted-foreground transition-colors hover:bg-fill-hover hover:text-foreground"
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

          <div className="mt-2">
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
                  <DropdownMenu>
                    <DropdownMenuTrigger
                      render={
                        <Button
                          variant="default"
                          size="icon-sm"
                          aria-label="Space options"
                          className="text-muted-foreground"
                        >
                          <DotsThreeIcon size={16} weight="bold" />
                        </Button>
                      }
                    />
                    {/* Only what the + does not already do. */}
                    <DropdownMenuContent
                      align="end"
                      side="bottom"
                      className="w-fit"
                    >
                      <DropdownMenuItem onClick={navigateToSpaces}>
                        Browse spaces…
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </div>
              }
            />
            {spacesExpanded && (
              <div className="flex flex-col gap-px">
                {starredSpaces.map((channel) => (
                  <SpaceRow
                    key={channel.id}
                    channel={channel}
                    isActive={channel.id === activeChannelId}
                    unread={isChannelUnread(channel.id)}
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
      </div>
      <CreateChannelModal open={createOpen} onOpenChange={setCreateOpen} />
      <EditListItemAppearanceDialog
        surface="sidebar"
        open={appearanceOpen}
        onOpenChange={setAppearanceOpen}
      />
    </Autocomplete>
  );
}
