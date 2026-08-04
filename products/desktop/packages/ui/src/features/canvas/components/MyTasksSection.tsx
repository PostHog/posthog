import { CaretRightIcon } from "@phosphor-icons/react";
import {
  buildChannelItems,
  type ChannelItemModel,
} from "@posthog/core/canvas/channelItems";
import { cn } from "@posthog/quill";
import { useArchivedTaskIds } from "@posthog/ui/features/archive/useArchivedTaskIds";
import { useArchiveTask } from "@posthog/ui/features/archive/useArchiveTask";
import type { ChannelItemActions } from "@posthog/ui/features/canvas/components/ChannelItemRow";
import { ChannelItemRow } from "@posthog/ui/features/canvas/components/ChannelItemRow";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import {
  normalizeChannelName,
  PERSONAL_CHANNEL_NAME,
  useTaskChannels,
} from "@posthog/ui/features/canvas/hooks/useTaskChannels";
import { useSpacesSidebarStore } from "@posthog/ui/features/canvas/stores/spacesSidebarStore";
import { usePinnedTasks } from "@posthog/ui/features/sidebar/usePinnedTasks";
import { useTasks } from "@posthog/ui/features/tasks/useTasks";
import { toast } from "@posthog/ui/primitives/toast";
import { useNavigate, useRouterState } from "@tanstack/react-router";
import { useMemo } from "react";

const MY_TASKS_CAP = 10;

/**
 * The viewer's tasks across every space, newest first — the same rows a
 * space's own list renders (status dot, badges, hover card), each wearing its
 * space's name in muted text. Rows open the task inside its space; tasks that
 * predate spaces (no backend channel) fall back to the personal space. The
 * header is a section label like "Spaces" below it, folding on click.
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
  const archivedTaskIds = useArchivedTaskIds();
  const { pinnedTaskIds, togglePin } = usePinnedTasks();
  const { archiveTask } = useArchiveTask({ navigateSpace: "website" });

  // Same item shape the space lists use, so the rows render identically.
  const items = useMemo<ChannelItemModel[]>(
    () =>
      buildChannelItems({
        dashboards: [],
        feedTasks: myTasks,
        archivedTaskIds,
        pinnedTaskIds,
        ownedBy: null,
      }).slice(0, MY_TASKS_CAP),
    [myTasks, archivedTaskIds, pinnedTaskIds],
  );

  // Each task's space: backend channel → display name → folder channel (which
  // the routes need). Unmapped tasks open under #me and carry no label.
  const spaceFor = useMemo(() => {
    const backendById = new Map(backendChannels.map((c) => [c.id, c]));
    const folderByName = new Map(
      folderChannels.map((c) => [normalizeChannelName(c.name), c]),
    );
    const me = folderChannels.find((c) => c.name === PERSONAL_CHANNEL_NAME);
    const byTaskId = new Map<
      string,
      { spaceName: string | null; folderId: string | undefined }
    >();
    for (const item of items) {
      const backend = item.task?.channel
        ? backendById.get(item.task.channel)
        : undefined;
      const spaceName = backend
        ? backend.channel_type === "personal"
          ? PERSONAL_CHANNEL_NAME
          : backend.name
        : null;
      const folder = spaceName
        ? folderByName.get(normalizeChannelName(spaceName))
        : undefined;
      byTaskId.set(item.id, { spaceName, folderId: (folder ?? me)?.id });
    }
    return byTaskId;
  }, [items, backendChannels, folderChannels]);

  const actions = useMemo<ChannelItemActions>(
    () => ({
      open: (item) => {
        const folderId = spaceFor.get(item.id)?.folderId;
        if (!folderId) return;
        void navigate({
          to: "/website/$channelId/tasks/$taskId",
          params: { channelId: folderId, taskId: item.id },
        });
      },
      togglePin: (item) => {
        togglePin(item.id).catch(() => {
          toast.error("Couldn't update pin");
        });
      },
      archive: (item) => {
        void archiveTask({ taskId: item.id });
      },
      // Tasks only here — canvases (the deletable kind) never appear.
      remove: () => {},
    }),
    [spaceFor, navigate, togglePin, archiveTask],
  );

  return (
    <div className="flex flex-col gap-px">
      {/* Same section-label shape and type as the "Spaces" header below it,
          with a fold caret. */}
      <button
        type="button"
        aria-expanded={open}
        onClick={toggleMyTasks}
        className="flex w-full items-center gap-1 px-1 pb-1.5 text-[12px] text-muted-foreground transition-colors hover:text-foreground"
      >
        <CaretRightIcon
          size={10}
          className={cn("transition-transform", open && "rotate-90")}
        />
        My tasks
      </button>

      {open && (
        <div className="flex flex-col gap-px pb-1">
          {items.length === 0 ? (
            <div className="px-2 py-1.5 text-[12px] text-muted-foreground">
              No tasks yet
            </div>
          ) : (
            items.map((item) => (
              <ChannelItemRow
                key={item.key}
                item={item}
                channelId={spaceFor.get(item.id)?.folderId}
                isActive={pathname.endsWith(`/tasks/${item.id}`)}
                actions={actions}
                contextLabel={spaceFor.get(item.id)?.spaceName ?? undefined}
              />
            ))
          )}
        </div>
      )}
    </div>
  );
}
