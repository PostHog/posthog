import { CaretRightIcon } from "@phosphor-icons/react";
import { Button, cn } from "@posthog/quill";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import {
  normalizeChannelName,
  PERSONAL_CHANNEL_NAME,
  useTaskChannels,
} from "@posthog/ui/features/canvas/hooks/useTaskChannels";
import { useSpacesSidebarStore } from "@posthog/ui/features/canvas/stores/spacesSidebarStore";
import { SidebarItem } from "@posthog/ui/features/sidebar/components/SidebarItem";
import { useTasks } from "@posthog/ui/features/tasks/useTasks";
import { useNavigate, useRouterState } from "@tanstack/react-router";
import { useMemo } from "react";

const MY_TASKS_CAP = 10;

/**
 * The viewer's tasks across every space, newest first, each wearing its
 * space's name in muted text on the right. Rows open the task inside its
 * space; tasks that predate spaces (no backend channel) fall back to the
 * personal space. Same folding header shape as the space rows below it.
 */
export function MyTasksSection() {
  const open = useSpacesSidebarStore((s) => s.openMyTasks);
  const toggleMyTasks = useSpacesSidebarStore((s) => s.toggleMyTasks);
  const navigate = useNavigate();
  const pathname = useRouterState({ select: (s) => s.location.pathname });

  // useTasks() without showAllUsers is already scoped to the viewer.
  const { data: myTasks = [] } = useTasks();
  const { channels: backendChannels } = useTaskChannels({ enabled: open });
  const { channels: folderChannels } = useChannels();

  const rows = useMemo(() => {
    const backendById = new Map(backendChannels.map((c) => [c.id, c]));
    const folderByName = new Map(
      folderChannels.map((c) => [normalizeChannelName(c.name), c]),
    );
    const me = folderChannels.find((c) => c.name === PERSONAL_CHANNEL_NAME);
    return [...myTasks]
      .sort(
        (a, b) =>
          (Date.parse(b.updated_at) || 0) - (Date.parse(a.updated_at) || 0),
      )
      .slice(0, MY_TASKS_CAP)
      .map((task) => {
        const backend = task.channel
          ? backendById.get(task.channel)
          : undefined;
        const spaceName = backend
          ? backend.channel_type === "personal"
            ? PERSONAL_CHANNEL_NAME
            : backend.name
          : null;
        const folder = spaceName
          ? folderByName.get(normalizeChannelName(spaceName))
          : undefined;
        return {
          task,
          spaceName,
          // The route needs the folder channel; unmapped tasks open under #me.
          folderId: (folder ?? me)?.id,
        };
      });
  }, [myTasks, backendChannels, folderChannels]);

  return (
    <div className="flex flex-col gap-px">
      {/* Same shape as a space row, so the carets line up. */}
      <Button
        variant="default"
        left
        aria-expanded={open}
        onClick={toggleMyTasks}
        className="w-full gap-1.5 text-left"
      >
        <CaretRightIcon
          size={12}
          className={cn(
            "shrink-0 text-muted-foreground transition-transform",
            open && "rotate-90",
          )}
        />
        <span className="min-w-0 flex-1 truncate font-medium text-[13px] text-muted-foreground group-hover/button:text-foreground">
          My tasks
        </span>
      </Button>

      {open && (
        <div className="flex flex-col gap-px pb-1 pl-5">
          {rows.length === 0 ? (
            <div className="px-2 py-1.5 text-[12px] text-muted-foreground">
              No tasks yet
            </div>
          ) : (
            rows.map(({ task, spaceName, folderId }) => (
              <SidebarItem
                key={task.id}
                depth={0}
                label={<span>{task.title || "Untitled task"}</span>}
                isActive={pathname.endsWith(`/tasks/${task.id}`)}
                onClick={
                  folderId
                    ? () =>
                        void navigate({
                          to: "/website/$channelId/tasks/$taskId",
                          params: { channelId: folderId, taskId: task.id },
                        })
                    : undefined
                }
                endContent={
                  spaceName ? (
                    <span className="ml-1 max-w-20 shrink-0 truncate text-[11px] text-muted-foreground">
                      {spaceName}
                    </span>
                  ) : undefined
                }
              />
            ))
          )}
        </div>
      )}
    </div>
  );
}
