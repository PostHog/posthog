import {
  buildChannelItems,
  type ChannelItemModel,
  type ChannelItemOwner,
  type ChannelSessionFacts,
  type ChannelWorkspaceFacts,
} from "@posthog/core/canvas/channelItems";
import { formatBulkResult } from "@posthog/core/sidebar/selection";
import { useArchivedTaskIds } from "@posthog/ui/features/archive/useArchivedTaskIds";
import { useArchiveTask } from "@posthog/ui/features/archive/useArchiveTask";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
import type { ChannelItemActions } from "@posthog/ui/features/canvas/components/ChannelItemRow";
import { deleteCanvasWithUndo } from "@posthog/ui/features/canvas/deleteCanvasWithUndo";
import { useChannelFeed } from "@posthog/ui/features/canvas/hooks/useChannelFeed";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useChannelTasks } from "@posthog/ui/features/canvas/hooks/useChannelTasks";
import {
  useDashboardMutations,
  useDashboards,
} from "@posthog/ui/features/canvas/hooks/useDashboards";
import { usePinnedTasks } from "@posthog/ui/features/sidebar/usePinnedTasks";
import { useSidebarSessionMap } from "@posthog/ui/features/sidebar/useSidebarSessionMap";
import { useTaskViewed } from "@posthog/ui/features/sidebar/useTaskViewed";
import { useTasks } from "@posthog/ui/features/tasks/useTasks";
import { useWorkspaces } from "@posthog/ui/features/workspace/useWorkspace";
import { toast } from "@posthog/ui/primitives/toast";
import { useNavigate } from "@tanstack/react-router";
import { useMemo } from "react";

/**
 * A channel's canvases + task feed as merged items, most recently active first, plus the
 * row actions and the viewer's identity for the recent-list filters.
 *
 * The channel is looked up in the channels list to establish its identity
 * (personal vs public). While it's unknown the hook reports loading and yields
 * nothing — which keeps the personal-channel ownership filter from running
 * against an identity we haven't established yet.
 */
export function useChannelSessionFacts(): ChannelSessionFacts {
  const sessions = useSidebarSessionMap();
  const { timestamps } = useTaskViewed();
  const { data: workspaces } = useWorkspaces();

  return useMemo<ChannelSessionFacts>(() => {
    const needsInputTaskIds = new Set<string>();
    for (const [taskId, session] of sessions) {
      if ((session.pendingPermissions?.size ?? 0) > 0) {
        needsInputTaskIds.add(taskId);
      }
    }
    const workspaceByTaskId = new Map<string, ChannelWorkspaceFacts>();
    for (const [taskId, workspace] of Object.entries(workspaces ?? {})) {
      workspaceByTaskId.set(taskId, {
        mode: workspace.mode,
        folderPath: workspace.folderPath,
        isScratch: workspace.isScratch,
        // The linked branch wins: a worktree's own branch is where the work is
        // only until it is linked to the branch the PR is on.
        branch: workspace.linkedBranch ?? workspace.branchName ?? undefined,
      });
    }
    return {
      needsInputTaskIds,
      viewedTimestamps: timestamps,
      workspaceByTaskId,
    };
  }, [sessions, timestamps, workspaces]);
}

export function useChannelItems(channelId: string): {
  items: ChannelItemModel[];
  actions: ChannelItemActions;
  /** Who the viewer is, for the created-by filter. */
  me: ChannelItemOwner;
  isLoading: boolean;
  /** The channel id resolves to no channel in this project. */
  channelMissing: boolean;
} {
  const navigate = useNavigate();

  const { channels, isLoading: channelsLoading } = useChannels();
  const channel = channels.find((c) => c.id === channelId);
  const identityKnown = channel !== undefined;
  const isPersonal = channel?.channelType === "personal";

  const { dashboards, isLoading: dashboardsLoading } = useDashboards(channelId);
  const { tasks: feedTasks, isLoading: feedLoading } =
    useChannelFeed(channelId);
  const { tasks: filedTaskRecords, isLoading: filedTasksLoading } =
    useChannelTasks(channelId);
  const { data: allTasks = [], isLoading: allTasksLoading } = useTasks({
    showAllUsers: true,
  });
  const archivedTaskIds = useArchivedTaskIds();
  const { pinnedTaskIds, togglePin, setPinnedMany } = usePinnedTasks();
  const { archiveTask } = useArchiveTask({ navigateUnscoped: true });
  const {
    setPinned: setCanvasPinned,
    fileDashboard,
    invalidateDashboards,
  } = useDashboardMutations();
  const client = useOptionalAuthenticatedClient();
  const { data: currentUser, isLoading: viewerLoading } = useCurrentUser({
    client,
  });

  // What the filters ask about beyond the task itself: a live session's
  // permission prompt, when you last looked, and where the workspace is. The
  // session map is the sidebar's own subscription, which ignores the streamed
  // events a turn fires and only wakes on the fields a row reads.
  const sessionFacts = useChannelSessionFacts();
  const meUuid = currentUser?.uuid ?? null;
  const me = useMemo<ChannelItemOwner>(() => ({ uuid: meUuid }), [meUuid]);
  // Only a uuid establishes identity — ownership compares uuids, so a viewer
  // resolved without one can't be matched against anything and reads as unknown.
  const viewerKnown = meUuid != null;

  const items = useMemo<ChannelItemModel[]>(() => {
    if (!identityKnown || (isPersonal && !viewerKnown)) return [];

    const tasksById = new Map(allTasks.map((task) => [task.id, task]));
    const mergedTasks = [...feedTasks];
    const seenTaskIds = new Set(feedTasks.map((task) => task.id));
    for (const record of filedTaskRecords) {
      const task = tasksById.get(record.taskId);
      if (task && !seenTaskIds.has(task.id)) {
        mergedTasks.push(task);
        seenTaskIds.add(task.id);
      }
    }

    return buildChannelItems({
      dashboards,
      feedTasks: mergedTasks,
      archivedTaskIds,
      pinnedTaskIds,
      // The personal channel is yours — but don't filter until we know
      // who you are, or #me flashes everyone's items on a cold load.
      ownedBy: isPersonal && viewerKnown ? me : null,
      sessionFacts,
    });
  }, [
    identityKnown,
    sessionFacts,
    dashboards,
    feedTasks,
    filedTaskRecords,
    allTasks,
    archivedTaskIds,
    pinnedTaskIds,
    isPersonal,
    viewerKnown,
    me,
  ]);

  const actions = useMemo<ChannelItemActions>(
    () => ({
      open: (item) => {
        if (item.kind === "canvas") {
          void navigate({
            to: "/spaces/$channelId/dashboards/$dashboardId",
            params: { channelId, dashboardId: item.id },
          });
        } else {
          void navigate({
            to: "/spaces/$channelId/tasks/$taskId",
            params: { channelId, taskId: item.id },
          });
        }
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
      // One request for the sessions and one per canvas, rather than a toggle
      // per row: pinning is a scoped mutation, so a row-at-a-time batch waits
      // out a round trip for each one.
      setPinned: (items, pinned) => {
        const taskIds = items
          .filter((item) => item.kind === "task")
          .map((item) => item.id);
        const canvases = items.filter((item) => item.kind === "canvas");

        // setPinnedMany settles every request itself and reports failures in
        // `failed` rather than rejecting, so a shared Promise.all would read a
        // failed session batch as success — check its result on its own.
        if (taskIds.length > 0) {
          setPinnedMany(taskIds, pinned)
            .then(({ succeeded, failed }) => {
              if (failed.length === 0) return;
              const { message } = formatBulkResult(
                pinned ? "pinned" : "unpinned",
                { succeeded: succeeded.length, failed: failed.length },
              );
              toast.error(message);
            })
            .catch(() => {
              toast.error(`Couldn't ${pinned ? "pin" : "unpin"} the sessions`);
            });
        }

        const canvasPins = canvases.map((canvas) =>
          setCanvasPinned(canvas.id, pinned),
        );
        if (canvasPins.length > 0) {
          Promise.all(canvasPins).catch(() => {
            toast.error("Couldn't update pin");
          });
        }
      },
      archive: (item) => {
        void archiveTask({ taskId: item.id });
      },
      fileCanvas: async (item, targetChannelId) => {
        try {
          await fileDashboard(item.id, targetChannelId);
          const targetName = channels.find(
            (candidate) => candidate.id === targetChannelId,
          )?.name;
          toast.success(targetName ? `Filed to ${targetName}` : "Canvas filed");
        } catch (error) {
          toast.error("Couldn't file canvas", {
            description: error instanceof Error ? error.message : String(error),
          });
        }
      },
      // Canvases only, and through the shared undo window: the row disappears at
      // once and the host isn't told until the toast expires, so an accidental
      // delete costs nothing.
      remove: (item) => {
        if (item.kind !== "canvas") return;
        deleteCanvasWithUndo({
          dashboardId: item.id,
          channelId,
          name: item.title,
          surface: "sidebar",
          invalidate: invalidateDashboards,
        });
      },
    }),
    [
      channelId,
      navigate,
      setCanvasPinned,
      togglePin,
      setPinnedMany,
      archiveTask,
      fileDashboard,
      channels,
      invalidateDashboards,
    ],
  );

  // A channel that isn't in the list will never resolve, so stop reporting
  // loading and let the caller say so instead of spinning forever.
  const channelMissing = !channelsLoading && !channel;

  return {
    items,
    actions,
    me,
    isLoading:
      !channelMissing &&
      (channelsLoading ||
        !identityKnown ||
        dashboardsLoading ||
        feedLoading ||
        filedTasksLoading ||
        allTasksLoading ||
        (isPersonal && viewerLoading)),
    channelMissing,
  };
}
