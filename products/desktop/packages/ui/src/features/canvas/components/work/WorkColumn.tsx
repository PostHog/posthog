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
import type { TaskRowMenuProps } from "@posthog/ui/features/canvas/components/TaskRowMenu";
import { WorkItemRow } from "@posthog/ui/features/canvas/components/work/WorkItemRow";
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
import { ChromeBar } from "@posthog/ui/primitives/ChromeBar";
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

/** A section's label, foldable, with room for one control at its end. */
function SectionHeader({
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
    <div className="group/section flex items-center pr-1 pl-2">
      <button
        type="button"
        aria-expanded={expanded}
        onClick={onToggle}
        className="flex min-w-0 flex-1 items-center gap-1 rounded-sm text-left"
      >
        <Caret
          size={10}
          weight="bold"
          className="shrink-0 text-muted-foreground opacity-60 transition-opacity group-hover/section:opacity-100"
        />
        <MenuLabel className="px-0">{label}</MenuLabel>
      </button>
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

function RecentRows({
  items,
  activeKey,
  actions,
}: {
  items: RecentWorkItem[];
  activeKey: string | null;
  actions: ChannelItemActions;
}) {
  return (
    <div className="flex flex-col gap-px px-1.5">
      {items.map(({ item, channelId }) => (
        <WorkItemRow
          key={item.key}
          item={item}
          isActive={item.key === activeKey}
          onOpen={() => actions.open(item)}
          menu={
            {
              kind: item.kind,
              id: item.id,
              title: item.title,
              isPinned: item.pinned,
              task: item.task ?? undefined,
              channelId,
              onTogglePin: () => actions.togglePin(item),
              onArchive:
                item.kind === "task" ? () => actions.archive(item) : undefined,
            } satisfies TaskRowMenuProps
          }
        />
      ))}
    </div>
  );
}

/** One space. Same 28px line as a Recent row, so the two lists share a rhythm. */
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
    <button
      type="button"
      data-selected={isActive || undefined}
      className={cn(
        "group flex h-7 w-full min-w-0 items-center gap-2 rounded-md px-2 text-left text-[13px] transition-colors",
        "text-muted-foreground hover:bg-fill-hover hover:text-foreground",
        "data-selected:bg-fill-selected data-selected:font-medium data-selected:text-foreground",
        unread && !isActive && "font-medium text-foreground",
      )}
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
      <span className="min-w-0 flex-1 truncate">{channel.name}</span>
      {unread && !isActive && (
        <span
          role="img"
          aria-label="Unread"
          className="size-1.5 shrink-0 rounded-full bg-primary"
        />
      )}
    </button>
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
    <div className="mx-2 mt-1 mb-2 flex flex-col overflow-hidden rounded-md border border-border bg-background">
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
            className="text-[13px]"
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
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
          <p className="px-2 py-2 text-muted-foreground text-xs">
            {needle ? "No space by that name." : "Every space is already here."}
          </p>
        ) : (
          shown.map((channel) => (
            <button
              key={channel.id}
              type="button"
              className="group/add flex h-7 w-full min-w-0 items-center gap-2 rounded-md px-2 text-left text-[13px] text-muted-foreground transition-colors hover:bg-fill-hover hover:text-foreground"
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
        className="flex items-center gap-1.5 border-border border-t px-3 py-2 text-left text-[13px] text-muted-foreground transition-colors hover:bg-fill-hover hover:text-foreground"
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
 */
export function WorkColumn() {
  const [recentExpanded, setRecentExpanded] = useState(false);
  const [spacesExpanded, setSpacesExpanded] = useState(true);
  const [adding, setAdding] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);

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

  // #me leads, then the starred spaces in the list's own (name) order.
  const starredSpaces = useMemo(
    () => [
      ...channels.filter((c) => c.channelType === "personal"),
      ...channels.filter((c) => c.channelType !== "personal" && c.starred),
    ],
    [channels],
  );
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

  const shownItems = recentExpanded
    ? items
    : items.slice(0, RECENT_COLLAPSED_COUNT);
  const canExpandRecent = items.length > RECENT_COLLAPSED_COUNT;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <ChromeBar>
        <h2 className="font-bold text-base">Work</h2>
      </ChromeBar>
      <div className="scroll-mask-8 min-h-0 flex-1 overflow-y-auto pt-1 pb-3">
        <SectionHeader
          label="Recent"
          expanded={recentExpanded}
          onToggle={() => setRecentExpanded((value) => !value)}
          trailing={
            canExpandRecent ? (
              <button
                type="button"
                className="rounded-sm px-1 text-[11px] text-muted-foreground tabular-nums transition-colors hover:text-foreground"
                onClick={() => setRecentExpanded((value) => !value)}
              >
                {recentExpanded ? "Fewer" : `All ${items.length}`}
              </button>
            ) : null
          }
        />
        {isLoading && items.length === 0 ? (
          <div className="flex flex-col gap-2 px-4 py-1.5">
            <Skeleton className="h-3.5 w-4/5" />
            <Skeleton className="h-3.5 w-3/5" />
            <Skeleton className="h-3.5 w-2/3" />
          </div>
        ) : items.length === 0 ? (
          <p className="px-4 py-1.5 text-muted-foreground text-xs">
            Sessions and canvases you open show up here.
          </p>
        ) : (
          <RecentRows
            items={shownItems}
            activeKey={activeKey}
            actions={actions}
          />
        )}

        <div className="mt-3">
          <SectionHeader
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
              <div className="flex flex-col gap-px px-1.5">
                {starredSpaces.map((channel) => (
                  <SpaceRow
                    key={channel.id}
                    channel={channel}
                    isActive={channel.id === activeChannelId}
                    unread={isChannelUnread(channel.id)}
                  />
                ))}
                {starredSpaces.length <= 1 && !adding && (
                  <button
                    type="button"
                    className="mx-1 mt-1 flex items-center gap-1.5 rounded-md border border-border border-dashed px-2 py-1.5 text-left text-[13px] text-muted-foreground transition-colors hover:border-foreground/40 hover:text-foreground"
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
      </div>
      <CreateChannelModal open={createOpen} onOpenChange={setCreateOpen} />
    </div>
  );
}
