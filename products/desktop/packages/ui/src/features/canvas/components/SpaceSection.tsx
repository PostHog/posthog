import { CaretRightIcon, GearSixIcon } from "@phosphor-icons/react";
import { isOwnedBy } from "@posthog/core/canvas/channelItems";
import { Button, cn, Skeleton } from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { ChannelItemRow } from "@posthog/ui/features/canvas/components/ChannelItemRow";
import { channelGlyph } from "@posthog/ui/features/canvas/components/channelGlyph";
import { useChannelItems } from "@posthog/ui/features/canvas/hooks/useChannelItems";
import type { Channel } from "@posthog/ui/features/canvas/hooks/useChannels";
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

/**
 * One pinned space in the static sidebar. The whole row is one click target:
 * it folds the space's task list open and closed (caret included — no separate
 * hover zones). The hover gear on the right is what opens the space itself in
 * the main view, where the header tabs (Feed/Context/Loops/Artifacts) live.
 * #me wears its lock in the same right-hand well, stepping aside for the gear
 * on hover.
 *
 * Expand state is local view state in `spacesSidebarStore`; the space's
 * presence in the sidebar is its star, managed from the All spaces directory.
 */
export function SpaceSection({ channel }: { channel: Channel }) {
  const open = useSpacesSidebarStore((s) => !!s.openSections[channel.id]);
  const toggle = useSpacesSidebarStore((s) => s.toggle);
  const onlyMine = useSpacesSidebarStore((s) => s.onlyMyTasks);
  const setCurrentChannel = useCurrentChannelStore((s) => s.setCurrentChannel);
  const navigate = useNavigate();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const base = `/website/${channel.id}`;
  const isActive = pathname === base || pathname.startsWith(`${base}/`);
  const isUnread = useIsChannelUnread()(channel.name);
  // Only #me has a glyph under the layout (its lock) — same rule as
  // ChannelBackRow; it sits in the trailing well, not in front of the name.
  const glyph = channelGlyph(channel.name, {
    size: 14,
    space: true,
    className: "text-muted-foreground",
  });

  const { items, actions, isLoading, me } = useChannelItems(channel.id);
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

  // The sidebar-wide "My tasks" toggle narrows every space's list to items the
  // viewer created — the same fail-closed ownership rule #me itself uses.
  const visibleItems = useMemo(
    () => (onlyMine ? items.filter((i) => isOwnedBy(i, me)) : items),
    [items, onlyMine, me],
  );
  const sectionItems = useMemo(
    () =>
      [
        ...visibleItems.filter((i) => i.pinned),
        ...visibleItems.filter((i) => !i.pinned),
      ].slice(0, RECENTS_CAP),
    [visibleItems],
  );
  const overflowCount = visibleItems.length - sectionItems.length;

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
          aria-expanded={open}
          data-selected={isActive || undefined}
          className="w-full gap-1.5 text-left data-selected:bg-fill-selected"
          onClick={() => toggle(channel.id)}
        >
          <CaretRightIcon
            size={12}
            className={cn(
              "shrink-0 text-muted-foreground transition-transform",
              open && "rotate-90",
            )}
          />
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
          {/* Trailing well, reserved so the name truncates clear of the lock
              and hover gear rather than shifting when they appear. */}
          <span aria-hidden className="size-6 shrink-0" />
        </Button>
        {/* Overlays, not children — the row is a button already. The lock
            yields its spot to the gear on hover so the well never doubles up. */}
        {glyph && (
          <span
            aria-hidden
            className="-translate-y-1/2 pointer-events-none absolute top-1/2 right-[11px] flex items-center transition-opacity group-hover/space:opacity-0"
          >
            {glyph}
          </span>
        )}
        <Button
          variant="default"
          size="icon-sm"
          aria-label={`Open ${channel.name}`}
          onClick={openSpace}
          className="-translate-y-1/2 absolute top-1/2 right-[6px] text-muted-foreground opacity-0 transition-opacity focus-visible:opacity-100 group-hover/space:opacity-100"
        >
          <GearSixIcon size={14} />
        </Button>
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
              {onlyMine ? "None of your tasks here" : "No tasks yet"}
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
                  View all ({visibleItems.length})
                </Button>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
