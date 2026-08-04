import { CaretRightIcon, StarIcon } from "@phosphor-icons/react";
import { Button, cn, Skeleton } from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { ChannelItemRow } from "@posthog/ui/features/canvas/components/ChannelItemRow";
import { channelGlyph } from "@posthog/ui/features/canvas/components/channelGlyph";
import { useChannelItems } from "@posthog/ui/features/canvas/hooks/useChannelItems";
import { useChannelStarToggle } from "@posthog/ui/features/canvas/hooks/useChannelStars";
import type { Channel } from "@posthog/ui/features/canvas/hooks/useChannels";
import { PERSONAL_CHANNEL_NAME } from "@posthog/ui/features/canvas/hooks/useTaskChannels";
import { useIsChannelUnread } from "@posthog/ui/features/canvas/hooks/useUnreadChannels";
import { useCurrentChannelStore } from "@posthog/ui/features/canvas/stores/currentChannelStore";
import { useSpacesSidebarStore } from "@posthog/ui/features/canvas/stores/spacesSidebarStore";
import { useCommandCenterStore } from "@posthog/ui/features/command-center/commandCenterStore";
import { useRenameTask } from "@posthog/ui/features/tasks/useTaskMutations";
import { useTasks } from "@posthog/ui/features/tasks/useTasks";
import { toast } from "@posthog/ui/primitives/toast";
import { track } from "@posthog/ui/shell/analytics";
import { useNavigate, useRouterState } from "@tanstack/react-router";
import { useMemo, useState } from "react";

const RECENTS_CAP = 10;

// An overlay rather than a sibling: the header button fills the row, and
// nesting the star inside it would be a button within a button (see
// ChannelBackRow). Hidden at rest — every pinned row wearing a star reads as a
// column of noise; the row being here at all already says "pinned".
function RowStar({ channel }: { channel: Channel }) {
  const { isStarred, toggleStar } = useChannelStarToggle(channel);
  return (
    <Button
      variant="default"
      size="icon-sm"
      aria-label={isStarred ? "Unpin space" : "Pin space"}
      onClick={() => {
        track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
          action_type: isStarred ? "unstar" : "star",
          surface: "sidebar",
          channel_id: channel.id,
        });
        toggleStar();
      }}
      className={cn(
        "-translate-y-1/2 absolute top-1/2 right-[6px] text-muted-foreground transition-opacity",
        "opacity-0 focus-visible:opacity-100 group-hover/space:opacity-100",
      )}
    >
      <StarIcon size={14} weight={isStarred ? "fill" : "regular"} />
    </Button>
  );
}

/**
 * One pinned space in the static sidebar. The row itself opens the space (its
 * feed) and expands it; the disclosure caret toggles the expansion alone, so
 * you can fold a space away without leaving where you are. Beneath it, the
 * space's tasks as ChannelItemRows — the space's pages (Feed/Recents/…) live
 * in the channel header's tabs, not here.
 *
 * Expand state is local view state in `spacesSidebarStore`; the space's
 * presence in the sidebar is its star.
 */
export function SpaceSection({ channel }: { channel: Channel }) {
  const open = useSpacesSidebarStore((s) => !!s.openSections[channel.id]);
  const toggle = useSpacesSidebarStore((s) => s.toggle);
  const setOpen = useSpacesSidebarStore((s) => s.setOpen);
  const setCurrentChannel = useCurrentChannelStore((s) => s.setCurrentChannel);
  const navigate = useNavigate();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const base = `/website/${channel.id}`;
  const isActive = pathname === base || pathname.startsWith(`${base}/`);
  const isUnread = useIsChannelUnread()(channel.name);
  const isPersonal = channel.name === PERSONAL_CHANNEL_NAME;
  // Only #me carries a glyph under the layout (its lock); a cube in front of
  // every space said nothing the name didn't — same rule as ChannelBackRow.
  const glyph = channelGlyph(channel.name, {
    size: 14,
    space: true,
    className: "text-muted-foreground",
  });

  const { items, actions, isLoading } = useChannelItems(channel.id);
  const [editingTaskId, setEditingTaskId] = useState<string | null>(null);
  const { renameTask } = useRenameTask();

  const { data: allTasks = [] } = useTasks({ showAllUsers: true });
  const allTaskIds = useMemo(
    () => new Set(allTasks.map((t) => t.id)),
    [allTasks],
  );
  const commandCenterCells = useCommandCenterStore((state) => state.cells);
  const assignTaskToCommandCenter = useCommandCenterStore(
    (state) => state.assignTask,
  );

  const activeKey = useMemo(() => {
    const dashboard = pathname.match(/\/dashboards\/([^/]+)$/);
    if (dashboard) return `canvas:${dashboard[1]}`;
    const task = pathname.match(/\/tasks\/([^/]+)$/);
    return task ? `task:${task[1]}` : null;
  }, [pathname]);

  const sectionItems = useMemo(
    () =>
      [
        ...items.filter((i) => i.pinned),
        ...items.filter((i) => !i.pinned),
      ].slice(0, RECENTS_CAP),
    [items],
  );
  const overflowCount = items.length - sectionItems.length;

  const commandCenterAssigner = (taskId: string) => {
    const cellIndex = commandCenterCells.findIndex(
      (cellTaskId) => cellTaskId == null || !allTaskIds.has(cellTaskId),
    );
    if (cellIndex === -1) return undefined;
    return () => assignTaskToCommandCenter(cellIndex, taskId);
  };

  const openSpace = () => {
    track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
      action_type: "nav_click",
      surface: "sidebar",
      channel_id: channel.id,
    });
    setCurrentChannel(channel.id);
    setOpen(channel.id, true);
    void navigate({
      to: "/website/$channelId",
      params: { channelId: channel.id },
    });
  };

  return (
    <div>
      <div className="group/space relative">
        <Button
          variant="default"
          left
          data-selected={isActive || undefined}
          className="w-full gap-1.5 pl-7 text-left data-selected:bg-fill-selected"
          onClick={openSpace}
        >
          {glyph && (
            <span className="flex w-4 shrink-0 items-center justify-center">
              {glyph}
            </span>
          )}
          <span
            className={cn(
              "min-w-0 flex-1 truncate text-[13px]",
              // Bold is unread's alone; full contrast is shared with the space
              // you're in — the same vocabulary as the channel list rows.
              isUnread ? "font-bold" : "font-medium",
              isUnread || isActive
                ? "text-foreground"
                : "text-muted-foreground group-hover/button:text-foreground",
            )}
          >
            {channel.name}
          </span>
          {/* Star well, reserved so the name truncates before running under
              the hover star rather than shifting when it appears. */}
          {!isPersonal && <span aria-hidden className="size-6 shrink-0" />}
        </Button>
        {/* Overlays, not children — the row is a button already. */}
        <Button
          variant="default"
          size="icon-sm"
          aria-label={`${open ? "Collapse" : "Expand"} ${channel.name}`}
          aria-expanded={open}
          onClick={() => toggle(channel.id)}
          className="-translate-y-1/2 absolute top-1/2 left-px text-muted-foreground"
        >
          <CaretRightIcon
            size={12}
            className={cn("transition-transform", open && "rotate-90")}
          />
        </Button>
        {!isPersonal && <RowStar channel={channel} />}
      </div>

      {/* Tasks under the space, pinned first. Same inset as the channel
          groups' trees (pl-5). */}
      {open && (
        <div className="flex flex-col gap-px pb-1 pl-5">
          {isLoading && sectionItems.length === 0 ? (
            <div className="flex flex-col gap-2 px-2 py-2">
              <Skeleton className="h-3 w-3/4" />
              <Skeleton className="h-3 w-1/2" />
            </div>
          ) : sectionItems.length === 0 ? (
            <div className="px-2 py-1.5 text-[12px] text-muted-foreground">
              No tasks yet
            </div>
          ) : (
            <>
              {sectionItems.map((item) => (
                <ChannelItemRow
                  key={item.key}
                  item={item}
                  channelId={channel.id}
                  isActive={item.key === activeKey}
                  actions={actions}
                  isEditing={item.kind === "task" && editingTaskId === item.id}
                  onRename={
                    item.kind === "task"
                      ? () => setEditingTaskId(item.id)
                      : undefined
                  }
                  onAddToCommandCenter={
                    item.kind === "task" &&
                    !commandCenterCells.includes(item.id)
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
                            toast.error("Couldn't rename task", {
                              description:
                                error instanceof Error
                                  ? error.message
                                  : String(error),
                            });
                          }
                        }
                      : undefined
                  }
                  onEditCancel={() => setEditingTaskId(null)}
                />
              ))}
              {/* The list is a cap, not the whole story — the rest live on the
                  space's Recents page. */}
              {overflowCount > 0 && (
                <Button
                  variant="default"
                  size="sm"
                  className="justify-start text-[12px] text-muted-foreground"
                  onClick={() =>
                    void navigate({
                      to: "/website/$channelId/history",
                      params: { channelId: channel.id },
                    })
                  }
                >
                  View all ({items.length})
                </Button>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
