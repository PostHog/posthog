import {
  CaretRightIcon,
  CubeIcon,
  LinkIcon,
  PencilSimpleIcon,
  StarIcon,
  TrashIcon,
} from "@phosphor-icons/react";
import {
  Button,
  cn,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { ChannelItemRow } from "@posthog/ui/features/canvas/components/ChannelItemRow";
import { channelGlyph } from "@posthog/ui/features/canvas/components/channelGlyph";
import { RenameChannelModal } from "@posthog/ui/features/canvas/components/RenameChannelModal";
import { useChannelItems } from "@posthog/ui/features/canvas/hooks/useChannelItems";
import { useChannelStarToggle } from "@posthog/ui/features/canvas/hooks/useChannelStars";
import type { Channel } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useSpacesSidebarStore } from "@posthog/ui/features/canvas/stores/spacesSidebarStore";
import { copyChannelLink } from "@posthog/ui/features/canvas/utils/copyChannelLink";
import { useCommandCenterStore } from "@posthog/ui/features/command-center/commandCenterStore";
import { useRenameTask } from "@posthog/ui/features/tasks/useTaskMutations";
import { useTasks } from "@posthog/ui/features/tasks/useTasks";
import { toast } from "@posthog/ui/primitives/toast";
import { track } from "@posthog/ui/shell/analytics";
import { useRouterState } from "@tanstack/react-router";
import { useMemo, useState } from "react";

const RECENTS_CAP = 10;

/**
 * One pinned space in the static sidebar: an expandable header row, and beneath
 * it the space's tasks (the same `ChannelItemRow`s the channel pane renders).
 * Expand state is local view state in `spacesSidebarStore`; the space's
 * presence in the sidebar is the user's star.
 */
export function SpaceSection({ channel }: { channel: Channel }) {
  const open = useSpacesSidebarStore((s) => !!s.openSections[channel.id]);
  const toggle = useSpacesSidebarStore((s) => s.toggle);
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const base = `/website/${channel.id}`;
  const isActive = pathname === base || pathname.startsWith(`${base}/`);

  const { items, actions, isLoading } = useChannelItems(channel.id);
  const { toggleStar } = useChannelStarToggle(channel);
  const [menuOpen, setMenuOpen] = useState(false);
  const [renameOpen, setRenameOpen] = useState(false);
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

  const commandCenterAssigner = (taskId: string) => {
    const cellIndex = commandCenterCells.findIndex(
      (cellTaskId) => cellTaskId == null || !allTaskIds.has(cellTaskId),
    );
    if (cellIndex === -1) return undefined;
    return () => assignTaskToCommandCenter(cellIndex, taskId);
  };

  const glyph = channelGlyph(channel.name, { size: 14, space: true }) ?? (
    <CubeIcon size={14} />
  );

  return (
    <div className="group/space">
      {/* Header: chevron toggles the task list; the row itself opens the space. */}
      <div className="flex w-full items-center">
        <button
          type="button"
          aria-label={open ? "Collapse space" : "Expand space"}
          aria-expanded={open}
          className="flex h-7 w-5 shrink-0 items-center justify-center text-muted-foreground hover:text-foreground"
          onClick={() => toggle(channel.id)}
        >
          <CaretRightIcon
            size={12}
            className={cn("transition-transform", open && "rotate-90")}
          />
        </button>
        <Button
          variant="default"
          size="default"
          left
          data-selected={isActive || undefined}
          className="min-w-0 flex-1 justify-start gap-2 data-selected:bg-fill-selected data-selected:text-foreground"
          onClick={() => toggle(channel.id)}
        >
          <span className="flex h-[18px] w-[18px] shrink-0 items-center justify-center text-muted-foreground group-hover/space:text-foreground">
            {glyph}
          </span>
          <span
            className={cn(
              "truncate font-medium text-[13px]",
              isActive && "font-semibold",
            )}
          >
            {channel.name}
          </span>
        </Button>
        <span className="ml-auto flex shrink-0 items-center pr-1">
          <DropdownMenu open={menuOpen} onOpenChange={setMenuOpen}>
            <DropdownMenuTrigger
              render={
                <button
                  type="button"
                  aria-label={`Actions for ${channel.name}`}
                  className={cn(
                    "flex h-5 w-5 items-center justify-center rounded text-gray-10 transition-opacity hover:bg-gray-4 focus:opacity-100",
                    menuOpen
                      ? "opacity-100"
                      : "opacity-0 group-hover/space:opacity-100",
                  )}
                />
              }
            >
              <span className="text-[13px] leading-none">···</span>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem
                onClick={() => {
                  track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
                    action_type: "unstar",
                    surface: "sidebar",
                    channel_id: channel.id,
                  });
                  toggleStar();
                }}
              >
                <StarIcon size={14} weight="fill" />
                Remove from sidebar
              </DropdownMenuItem>
              <DropdownMenuItem
                onClick={() => void copyChannelLink(channel.id, "sidebar")}
              >
                <LinkIcon size={14} />
                Copy link
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => setRenameOpen(true)}>
                <PencilSimpleIcon size={14} />
                Rename
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                variant="destructive"
                onClick={() =>
                  track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
                    action_type: "delete",
                    surface: "sidebar",
                    channel_id: channel.id,
                  })
                }
              >
                <TrashIcon size={14} />
                Delete space
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </span>
      </div>

      {/* Tasks under the space */}
      {open && (
        <div className="flex flex-col gap-px pb-1 pl-7">
          {isLoading && sectionItems.length === 0 ? (
            <div className="px-2 py-1.5 text-[12px] text-muted-foreground">
              Loading…
            </div>
          ) : sectionItems.length === 0 ? (
            <div className="px-2 py-1.5 text-[12px] text-muted-foreground">
              No tasks here yet.
            </div>
          ) : (
            sectionItems.map((item) => (
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
        </div>
      )}

      <RenameChannelModal
        open={renameOpen}
        onOpenChange={setRenameOpen}
        channel={channel}
      />
    </div>
  );
}
