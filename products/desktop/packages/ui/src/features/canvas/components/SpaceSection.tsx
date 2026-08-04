import { CaretRightIcon, GearSixIcon, PlusIcon } from "@phosphor-icons/react";
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
import { openTaskInput } from "@posthog/ui/router/useOpenTask";
import { track } from "@posthog/ui/shell/analytics";
import { useNavigate, useRouterState } from "@tanstack/react-router";
import { type Ref, useMemo, useState } from "react";

const INITIAL_ROWS = 5;

/**
 * One pinned space in the static sidebar. The whole row is one click target:
 * it folds the space's task list open and closed (caret included — no separate
 * hover zones). Hovering reveals two controls on the right: a plus that files
 * a new task into this space, and the gear that opens the space itself in the
 * main view, where the header tabs (Feed/Context/Loops/Artifacts) live. #me
 * wears its lock in the same right-hand well, stepping aside on hover.
 *
 * An opened space leads with its first five items and a "Show more" that
 * unfolds the rest inline — the pinned-spaces region around these sections is
 * the one scroll container, so no per-space scrollbars or page hops. A search
 * query (from the Spaces header) overrides both the fold and the cap:
 * matching spaces open on all their matches, spaces without any disappear.
 *
 * Expand state is local view state in `spacesSidebarStore`; the space's
 * presence in the sidebar is its star, managed from the All spaces directory.
 */
export function SpaceSection({
  channel,
  dragHandleRef,
  query,
}: {
  channel: Channel;
  /**
   * From the sortable wrapper (SpacesSidebarNav): binding the header row as
   * the drag handle keeps the task rows free for their own native drag (into
   * the Command Center) without dnd-kit swallowing it.
   */
  dragHandleRef?: Ref<HTMLButtonElement>;
  /** Lowercased search from the Spaces header, applied across every space. */
  query?: string;
}) {
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

  // The sidebar-wide "Mine" toggle narrows every space's list to items the
  // viewer created — the same fail-closed ownership rule #me itself uses —
  // and the header search narrows it further by title.
  const searching = !!query;
  const visibleItems = useMemo(() => {
    const mine = onlyMine ? items.filter((i) => isOwnedBy(i, me)) : items;
    return query
      ? mine.filter((i) => i.title.toLowerCase().includes(query))
      : mine;
  }, [items, onlyMine, me, query]);
  const sectionItems = useMemo(
    () => [
      ...visibleItems.filter((i) => i.pinned),
      ...visibleItems.filter((i) => !i.pinned),
    ],
    [visibleItems],
  );
  // "Show more" unfolds the rest of the list inline; a search always shows
  // every match. Transient view state — a fresh mount starts compact.
  const [showAll, setShowAll] = useState(false);
  const displayItems =
    searching || showAll ? sectionItems : sectionItems.slice(0, INITIAL_ROWS);
  const hiddenCount = sectionItems.length - displayItems.length;

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

  // While searching, a space is its matches — none means the whole section
  // steps aside rather than listing an empty shell.
  if (searching && sectionItems.length === 0) return null;

  return (
    <div>
      <div className="group/space relative">
        <Button
          ref={dragHandleRef}
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
              and the two hover controls rather than shifting when they appear. */}
          <span aria-hidden className="h-6 w-12 shrink-0" />
        </Button>
        {/* Overlays, not children — the row is a button already. The lock
            yields its spot to the controls on hover so the well never doubles
            up. */}
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
          aria-label={`New task in ${channel.name}`}
          onClick={() => {
            track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
              action_type: "new_task_open",
              surface: "sidebar",
              channel_id: channel.id,
            });
            openTaskInput({ channelId: channel.id });
          }}
          className="-translate-y-1/2 absolute top-1/2 right-[30px] text-muted-foreground opacity-0 transition-opacity focus-visible:opacity-100 group-hover/space:opacity-100"
        >
          <PlusIcon size={14} />
        </Button>
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
          groups' trees (pl-5). A search opens every matching space. */}
      {(open || searching) && (
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
            displayItems.map((item) => (
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
                  item.kind === "task" && !commandCenterCells.includes(item.id)
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
            ))
          )}
          {/* The rest unfold in place; a search already shows every match. */}
          {!searching && (hiddenCount > 0 || showAll) && (
            <Button
              variant="default"
              size="sm"
              className="justify-start text-[12px] text-muted-foreground"
              onClick={() => setShowAll((prev) => !prev)}
            >
              {showAll ? "Show less" : `Show more (${hiddenCount})`}
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
