import { CaretLeftIcon, StarIcon } from "@phosphor-icons/react";
import {
  Button,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { CHANNEL_SECTIONS } from "@posthog/ui/features/canvas/channelSections";
import { ChannelItemRow } from "@posthog/ui/features/canvas/components/ChannelItemRow";
import { channelPageLabel } from "@posthog/ui/features/canvas/components/channelPages";
import { useChannelItems } from "@posthog/ui/features/canvas/hooks/useChannelItems";
import { useChannelStarToggle } from "@posthog/ui/features/canvas/hooks/useChannelStars";
import type { Channel } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import { useSpacesSidebarStore } from "@posthog/ui/features/canvas/stores/spacesSidebarStore";
import { useCommandCenterStore } from "@posthog/ui/features/command-center/commandCenterStore";
import { openSettings } from "@posthog/ui/features/settings/hooks/useOpenSettings";
import { useRenameTask } from "@posthog/ui/features/tasks/useTaskMutations";
import { useTasks } from "@posthog/ui/features/tasks/useTasks";
import { toast } from "@posthog/ui/primitives/toast";
import { track } from "@posthog/ui/shell/analytics";
import { useNavigate, useRouterState } from "@tanstack/react-router";
import { useMemo, useState } from "react";

const RECENTS_CAP = 10;

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
      className="-translate-y-1/2 absolute top-1/2 right-[6px] text-muted-foreground"
    >
      <StarIcon size={14} weight={isStarred ? "fill" : "regular"} />
    </Button>
  );
}

/**
 * One pinned space in the static sidebar: the channel's header row (a
 * full-width row like ChannelBackRow, expanding on click), and beneath it the
 * space's tasks rendered as ChannelItemRows. Expand state is local view state
 * in `spacesSidebarStore`; the space's presence in the sidebar is its star.
 */
export function SpaceSection({ channel }: { channel: Channel }) {
  const open = useSpacesSidebarStore((s) => !!s.openSections[channel.id]);
  const toggle = useSpacesSidebarStore((s) => s.toggle);
  const navigate = useNavigate();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const base = `/website/${channel.id}`;
  const isActive = pathname === base || pathname.startsWith(`${base}/`);
  const spacesLayout = useChannelsLayout();

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

  const commandCenterAssigner = (taskId: string) => {
    const cellIndex = commandCenterCells.findIndex(
      (cellTaskId) => cellTaskId == null || !allTaskIds.has(cellTaskId),
    );
    if (cellIndex === -1) return undefined;
    return () => assignTaskToCommandCenter(cellIndex, taskId);
  };

  return (
    <div className="relative">
      <Tooltip>
        <TooltipTrigger
          render={
            <Button
              variant="default"
              left
              aria-expanded={open}
              data-selected={isActive || undefined}
              className="w-full gap-1.5 text-left"
              onClick={() => toggle(channel.id)}
            >
              <CaretLeftIcon
                size={12}
                className={`shrink-0 text-muted-foreground transition-transform ${open ? "rotate-90" : ""}`}
              />
              <span className="min-w-0 flex-1 truncate font-medium text-[13px]">
                {channel.name}
              </span>
              {/* Star well, reserved so the row doesn't shift when a space is pinned */}
              <span aria-hidden className="size-6 shrink-0" />
            </Button>
          }
        />
        <TooltipContent side="bottom">{channel.name}</TooltipContent>
      </Tooltip>
      <RowStar channel={channel} />

      {/* Tabs + tasks under the space. The tab row mirrors the space pages
          (Feed/Context/Loops/Artifacts/Settings), each navigating to the
          space's own route; Settings opens the global settings as in the nav
          row, since a per-space settings sheet doesn't exist yet. */}
      {open && (
        <nav className="flex items-center gap-px pb-1 pl-7">
          <Button
            variant="default"
            size="sm"
            data-selected={pathname === `/website/${channel.id}` || undefined}
            className={
              pathname === `/website/${channel.id}` ? "bg-fill-selected" : ""
            }
            onClick={() =>
              void navigate({
                to: "/website/$channelId",
                params: { channelId: channel.id },
              })
            }
          >
            {channelPageLabel("home")}
          </Button>
          {CHANNEL_SECTIONS.filter(
            (s) => spacesLayout || s.key !== "loops",
          ).map((section) => {
            const href = `/website/${channel.id}/${section.key}`;
            const active = pathname === href;
            return (
              <Button
                key={section.key}
                variant="default"
                size="sm"
                data-selected={active || undefined}
                className={active ? "bg-fill-selected" : ""}
                onClick={() => {
                  if (section.key === "context") {
                    void navigate({
                      to: "/website/$channelId/context",
                      params: { channelId: channel.id },
                    });
                  } else if (section.key === "loops") {
                    void navigate({
                      to: "/website/$channelId/loops",
                      params: { channelId: channel.id },
                    });
                  } else if (section.key === "artifacts") {
                    void navigate({
                      to: "/website/$channelId/artifacts",
                      params: { channelId: channel.id },
                    });
                  } else {
                    void navigate({
                      to: "/website/$channelId/history",
                      params: { channelId: channel.id },
                    });
                  }
                }}
              >
                {section.label}
              </Button>
            );
          })}
          <Button
            variant="default"
            size="sm"
            onClick={() => openSettings("agents")}
          >
            Settings
          </Button>
        </nav>
      )}

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
    </div>
  );
}
