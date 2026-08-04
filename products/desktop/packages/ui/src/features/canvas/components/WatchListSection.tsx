import { CaretRightIcon, XIcon } from "@phosphor-icons/react";
import {
  buildChannelItems,
  type ChannelItemModel,
} from "@posthog/core/canvas/channelItems";
import { Button, cn, MenuLabel } from "@posthog/quill";
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
import { type DragEvent, useMemo, useState } from "react";

/**
 * A personal watch list: drag any task row onto the section (they all carry
 * the text/x-task-id payload) to keep a reference to it here, newest first.
 * Watching is a local-only pointer — the task stays in its space, and rows
 * render exactly like a space's own list, each wearing its space's name. The
 * hover × forgets the reference; the header is a MenuLabel section like the
 * code sidebar's "Sessions".
 */
export function WatchListSection() {
  const open = useSpacesSidebarStore((s) => s.openWatchList);
  const toggleWatchList = useSpacesSidebarStore((s) => s.toggleWatchList);
  const watchList = useSpacesSidebarStore((s) => s.watchList);
  const addToWatchList = useSpacesSidebarStore((s) => s.addToWatchList);
  const removeFromWatchList = useSpacesSidebarStore(
    (s) => s.removeFromWatchList,
  );
  const navigate = useNavigate();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const [isDropTarget, setIsDropTarget] = useState(false);

  // Anyone's task can be watched, so resolve against the full list.
  const { data: allTasks = [] } = useTasks({ showAllUsers: true });
  const { channels: backendChannels } = useTaskChannels({ enabled: open });
  const { channels: folderChannels } = useChannels();
  const archivedTaskIds = useArchivedTaskIds();
  const { pinnedTaskIds, togglePin } = usePinnedTasks();
  const { archiveTask } = useArchiveTask({ navigateSpace: "website" });

  // Same item shape the space lists use, held in watch-list order (newest
  // watched first) rather than the builder's recency sort.
  const items = useMemo<ChannelItemModel[]>(() => {
    const watched = new Set(watchList);
    const built = buildChannelItems({
      dashboards: [],
      feedTasks: allTasks.filter((t) => watched.has(t.id)),
      archivedTaskIds,
      pinnedTaskIds,
      ownedBy: null,
    });
    const byId = new Map(built.map((item) => [item.id, item]));
    return watchList.flatMap((id) => byId.get(id) ?? []);
  }, [watchList, allTasks, archivedTaskIds, pinnedTaskIds]);

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

  const handleDragOver = (e: DragEvent) => {
    if (!e.dataTransfer.types.includes("text/x-task-id")) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
    setIsDropTarget(true);
  };
  const handleDragLeave = (e: DragEvent) => {
    // dragleave fires when crossing into children; only clear on a real exit.
    if (e.currentTarget.contains(e.relatedTarget as Node | null)) return;
    setIsDropTarget(false);
  };
  const handleDrop = (e: DragEvent) => {
    setIsDropTarget(false);
    const taskId = e.dataTransfer.getData("text/x-task-id");
    if (!taskId) return;
    e.preventDefault();
    addToWatchList(taskId);
  };

  return (
    // biome-ignore lint/a11y/noStaticElementInteractions: drop target for task drags; every row inside stays keyboard-reachable
    <div
      className={cn(
        "flex flex-col gap-px rounded-md transition-colors",
        isDropTarget && "bg-fill-hover",
      )}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {/* Same section-label shape as the code sidebar's "Sessions" header,
          folding on click. */}
      <MenuLabel
        render={
          <button
            type="button"
            onClick={toggleWatchList}
            aria-expanded={open}
            className="flex w-full items-center gap-1.5"
          />
        }
      >
        Watch list
        <CaretRightIcon
          size={10}
          className={cn(
            "text-muted-foreground transition-transform",
            open && "rotate-90",
          )}
        />
      </MenuLabel>

      {open &&
        (items.length === 0 ? (
          <div className="px-2 pt-0.5 pb-2 text-[12px] text-muted-foreground">
            Drag a session here to keep an eye on it
          </div>
        ) : (
          <div className="flex flex-col gap-px pb-1">
            {items.map((item) => (
              // Overlay, not endContent: the row is a button already.
              <div key={item.key} className="group/watch relative">
                <ChannelItemRow
                  item={item}
                  channelId={spaceFor.get(item.id)?.folderId}
                  isActive={pathname.endsWith(`/tasks/${item.id}`)}
                  actions={actions}
                  contextLabel={spaceFor.get(item.id)?.spaceName ?? undefined}
                />
                <Button
                  variant="default"
                  size="icon-sm"
                  aria-label="Remove from watch list"
                  onClick={() => removeFromWatchList(item.id)}
                  className="-translate-y-1/2 absolute top-1/2 right-0.5 text-muted-foreground opacity-0 transition-opacity focus-visible:opacity-100 group-hover/watch:opacity-100"
                >
                  <XIcon size={12} />
                </Button>
              </div>
            ))}
          </div>
        ))}
    </div>
  );
}
