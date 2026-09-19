import {
  CaretDownIcon,
  CaretRightIcon,
  MagnifyingGlassIcon,
  PlusIcon,
  StarIcon,
  XIcon,
} from "@phosphor-icons/react";
import type { ChannelItemModel } from "@posthog/core/canvas/channelItems";
import {
  Autocomplete,
  AutocompleteList,
  Button,
  cn,
  InputGroup,
  InputGroupAddon,
  InputGroupInput,
  MenuLabel,
  Skeleton,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { useArchiveTask } from "@posthog/ui/features/archive/useArchiveTask";
import type { ChannelItemActions } from "@posthog/ui/features/canvas/components/ChannelItemRow";
import { CreateChannelModal } from "@posthog/ui/features/canvas/components/CreateChannelModal";
import { channelGlyph } from "@posthog/ui/features/canvas/components/channelGlyph";
import { SidebarSearchHeader } from "@posthog/ui/features/canvas/components/SidebarSearchHeader";
import type { TaskRowMenuProps } from "@posthog/ui/features/canvas/components/TaskRowMenu";
import { WorkItemRow } from "@posthog/ui/features/canvas/components/work/WorkItemRow";
import { WorkRowSurface } from "@posthog/ui/features/canvas/components/work/WorkRowSurface";
import { useChannelStarMutations } from "@posthog/ui/features/canvas/hooks/useChannelStars";
import {
  type Channel,
  useChannels,
} from "@posthog/ui/features/canvas/hooks/useChannels";
import { useDashboardMutations } from "@posthog/ui/features/canvas/hooks/useDashboards";
import {
  type RecentWorkItem,
  useRecentWorkItems,
} from "@posthog/ui/features/canvas/hooks/useRecentWorkItems";
import { useIsChannelUnread } from "@posthog/ui/features/canvas/hooks/useUnreadChannels";
import { useCurrentChannelStore } from "@posthog/ui/features/canvas/stores/currentChannelStore";
import { usePinnedTasks } from "@posthog/ui/features/sidebar/usePinnedTasks";
import { toast } from "@posthog/ui/primitives/toast";
import {
  navigateToChannel,
  navigateToChannelDashboard,
  navigateToChannelTask,
  navigateToTaskDetail,
} from "@posthog/ui/router/navigationBridge";
import { track } from "@posthog/ui/shell/analytics";
import { useRouterState } from "@tanstack/react-router";
import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";

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
        className="flex min-w-0 flex-1 items-center gap-1 rounded-sm py-1 hover:text-foreground"
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
 * Adding a space to the list, in place: a search over the spaces you have not
 * starred, where a click stars one and it takes its seat above. Only creating
 * a space needs a form, so only that opens a dialog.
 */
function AddSpacePanel({
  candidates,
  onStar,
  onCreate,
  onClose,
}: {
  candidates: Channel[];
  onStar: (channel: Channel) => void;
  onCreate: () => void;
  onClose: () => void;
}) {
  const [query, setQuery] = useState("");
  const inputRef = useRef<HTMLInputElement | null>(null);
  useEffect(() => {
    inputRef.current?.focus();
  }, []);
  const needle = query.trim().toLowerCase();
  const shown = needle
    ? candidates.filter((c) => c.name.toLowerCase().includes(needle))
    : candidates;

  return (
    <div className="my-1 flex flex-col overflow-hidden rounded-md border border-border bg-background">
      <div className="p-1.5">
        <InputGroup className="h-7">
          <InputGroupAddon>
            <MagnifyingGlassIcon size={13} aria-hidden />
          </InputGroupAddon>
          <InputGroupInput
            ref={inputRef}
            value={query}
            placeholder="Add a space…"
            aria-label="Search spaces to add"
            className="text-[12px]"
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              // The column's own list is listening for these; this input is a
              // surface of its own and keeps them.
              event.stopPropagation();
              if (event.key === "Escape") {
                event.preventDefault();
                onClose();
              }
            }}
          />
          <InputGroupAddon align="inline-end">
            <button
              type="button"
              aria-label="Close"
              className="flex size-5 items-center justify-center rounded-sm text-muted-foreground hover:text-foreground"
              onClick={onClose}
            >
              <XIcon size={12} />
            </button>
          </InputGroupAddon>
        </InputGroup>
      </div>
      <div className="flex max-h-56 flex-col gap-px overflow-y-auto px-1.5 pb-1">
        {shown.length === 0 ? (
          <p className="px-2 py-2 text-[12px] text-muted-foreground">
            {needle ? "No space by that name." : "Every space is already here."}
          </p>
        ) : (
          shown.map((channel) => (
            <button
              key={channel.id}
              type="button"
              className="group/add flex h-7 w-full min-w-0 items-center gap-2 rounded-md px-2 text-left font-medium text-[12px] text-muted-foreground leading-snug transition-colors hover:bg-fill-hover hover:text-foreground"
              onClick={() => onStar(channel)}
            >
              <span className="flex size-3.5 shrink-0 items-center justify-center">
                {channelGlyph(channel.name, {
                  size: 13,
                  space: false,
                  private: channel.channelType === "private",
                })}
              </span>
              <span className="min-w-0 flex-1 truncate">{channel.name}</span>
              <StarIcon
                size={12}
                className="shrink-0 opacity-0 transition-opacity group-hover/add:opacity-100"
                aria-hidden
              />
            </button>
          ))
        )}
      </div>
      <button
        type="button"
        className="flex items-center gap-1.5 border-border border-t px-3 py-2 text-left font-medium text-[12px] text-muted-foreground transition-colors hover:bg-fill-hover hover:text-foreground"
        onClick={onCreate}
      >
        <PlusIcon size={13} aria-hidden />
        Create a new space…
      </button>
    </div>
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
  const [recentExpanded, setRecentExpanded] = useState(false);
  const [spacesExpanded, setSpacesExpanded] = useState(true);
  const [adding, setAdding] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [_scrollRoot, setScrollRoot] = useState<HTMLDivElement | null>(null);

  const { items, isLoading } = useRecentWorkItems();
  const { channels } = useChannels();
  const { star } = useChannelStarMutations();
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
  const matchingItems = useMemo(
    () =>
      needle
        ? items.filter(({ item }) => item.title.toLowerCase().includes(needle))
        : items,
    [items, needle],
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
  const candidateSpaces = useMemo(
    () => channels.filter((c) => c.channelType !== "personal" && !c.starred),
    [channels],
  );

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

  const starSpace = (channel: Channel) => {
    track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
      action_type: "star",
      surface: "sidebar",
      channel_id: channel.id,
    });
    star(channel.id).catch(() => {
      toast.error("Couldn't add the space");
    });
  };

  // A search is the user asking for everything that matches, so it opens the
  // list rather than making them expand it first.
  const showAllRecent = recentExpanded || needle !== "";
  const shownItems = showAllRecent
    ? matchingItems
    : matchingItems.slice(0, RECENT_COLLAPSED_COUNT);
  const canExpandRecent =
    needle === "" && matchingItems.length > RECENT_COLLAPSED_COUNT;
  const optionValues = useMemo(
    () => [
      ...shownItems.map(({ item }) => item.key),
      ...starredSpaces.map((channel) => channel.id),
    ],
    [shownItems, starredSpaces],
  );

  const menuFor = (entry: RecentWorkItem): TaskRowMenuProps => ({
    kind: entry.item.kind,
    id: entry.item.id,
    title: entry.item.title,
    isPinned: entry.item.pinned,
    task: entry.item.task ?? undefined,
    channelId: entry.channelId,
    onTogglePin: () => actions.togglePin(entry.item),
    onArchive:
      entry.item.kind === "task"
        ? () => actions.archive(entry.item)
        : undefined,
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
            trailing={
              recentOpen && canExpandRecent ? (
                <button
                  type="button"
                  className="rounded-sm px-1 text-[11px] text-muted-foreground tabular-nums transition-colors hover:text-foreground"
                  onClick={() => setRecentExpanded((value) => !value)}
                >
                  {recentExpanded ? "Fewer" : `All ${matchingItems.length}`}
                </button>
              ) : null
            }
          />
          {recentOpen &&
            (isLoading && items.length === 0 ? (
              <div className="flex flex-col gap-2 px-2 py-1.5">
                <Skeleton className="h-3.5 w-4/5" />
                <Skeleton className="h-3.5 w-3/5" />
                <Skeleton className="h-3.5 w-2/3" />
              </div>
            ) : shownItems.length === 0 ? (
              <p className="px-2 py-1 text-[12px] text-muted-foreground">
                {needle
                  ? "Nothing here matches."
                  : "Sessions and canvases you open show up here."}
              </p>
            ) : (
              <div className="flex flex-col gap-px">
                {shownItems.map((entry) => (
                  <WorkItemRow
                    key={entry.item.key}
                    item={entry.item}
                    isActive={entry.item.key === activeKey}
                    onOpen={() => actions.open(entry.item)}
                    menu={menuFor(entry)}
                  />
                ))}
              </div>
            ))}

          <div className="mt-2">
            <SectionHeading
              label="Spaces"
              expanded={spacesExpanded}
              onToggle={() => setSpacesExpanded((value) => !value)}
              trailing={
                <IconAction
                  label={adding ? "Done adding" : "Add a space"}
                  active={adding}
                  onClick={() => {
                    setSpacesExpanded(true);
                    setAdding((value) => !value);
                  }}
                >
                  <PlusIcon size={14} />
                </IconAction>
              }
            />
            {spacesExpanded && (
              <>
                {adding && (
                  <AddSpacePanel
                    candidates={candidateSpaces}
                    onStar={starSpace}
                    onCreate={() => {
                      setAdding(false);
                      setCreateOpen(true);
                    }}
                    onClose={() => setAdding(false)}
                  />
                )}
                <div className="flex flex-col gap-px">
                  {starredSpaces.map((channel) => (
                    <SpaceRow
                      key={channel.id}
                      channel={channel}
                      isActive={channel.id === activeChannelId}
                      unread={isChannelUnread(channel.id)}
                    />
                  ))}
                  {starredSpaces.length <= 1 && !adding && needle === "" && (
                    <button
                      type="button"
                      className="mt-1 flex items-center gap-1.5 rounded-md border border-border border-dashed px-2 py-1.5 text-left font-medium text-[12px] text-muted-foreground transition-colors hover:border-foreground/40 hover:text-foreground"
                      onClick={() => setAdding(true)}
                    >
                      <PlusIcon size={13} aria-hidden />
                      Add the spaces you work in
                    </button>
                  )}
                </div>
              </>
            )}
          </div>
        </AutocompleteList>
      </div>
      <CreateChannelModal open={createOpen} onOpenChange={setCreateOpen} />
    </Autocomplete>
  );
}
