import {
  buildChannelItems,
  type ChannelItemModel,
  type ChannelItemOwner,
} from "@posthog/core/canvas/channelItems";
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
import {
  PERSONAL_CHANNEL_NAME,
  useBackendChannel,
} from "@posthog/ui/features/canvas/hooks/useTaskChannels";
import { usePinnedTasks } from "@posthog/ui/features/sidebar/usePinnedTasks";
import { useTasks } from "@posthog/ui/features/tasks/useTasks";
import { toast } from "@posthog/ui/primitives/toast";
import { useNavigate } from "@tanstack/react-router";
import { useMemo } from "react";

/**
 * A channel's canvases + task feed as merged, newest-first items, plus the row
 * actions and the viewer's identity for the recent-list filters.
 *
 * The channel's *name* is resolved here rather than accepted as an argument: it
 * feeds `useBackendChannel`, whose resolve-or-create effect provisions a backend
 * channel for any name it's handed. A caller with a half-loaded channel list has
 * nothing truthful to pass, and a placeholder would create a real channel named
 * after the placeholder. While the name is unknown the hook reports loading and
 * yields nothing — which also keeps the personal-channel ownership filter from
 * running against an identity we haven't established yet.
 */
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
  const channelName = channel?.name;
  const identityKnown = channelName !== undefined;
  const isPersonal = channelName === PERSONAL_CHANNEL_NAME;

  const { dashboards, isLoading: dashboardsLoading } = useDashboards(channelId);
  const { channel: backendChannel, isLoading: channelLoading } =
    useBackendChannel(channelName);
  const { tasks: feedTasks, isLoading: feedLoading } = useChannelFeed(
    backendChannel?.id,
  );
  const { tasks: filedTaskRecords, isLoading: filedTasksLoading } =
    useChannelTasks(channelId);
  const { data: allTasks = [], isLoading: allTasksLoading } = useTasks({
    showAllUsers: true,
  });
  const archivedTaskIds = useArchivedTaskIds();
  const { pinnedTaskIds, togglePin } = usePinnedTasks();
  const { archiveTask } = useArchiveTask({ navigateSpace: "website" });
  const { setPinned: setCanvasPinned, invalidateDashboards } =
    useDashboardMutations();
  const client = useOptionalAuthenticatedClient();
  const { data: currentUser, isLoading: viewerLoading } = useCurrentUser({
    client,
  });

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
    });
  }, [
    identityKnown,
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
            to: "/website/$channelId/dashboards/$dashboardId",
            params: { channelId, dashboardId: item.id },
          });
        } else {
          void navigate({
            to: "/website/$channelId/tasks/$taskId",
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
      archive: (item) => {
        void archiveTask({ taskId: item.id });
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
      archiveTask,
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
        channelLoading ||
        feedLoading ||
        filedTasksLoading ||
        allTasksLoading ||
        (isPersonal && viewerLoading)),
    channelMissing,
  };
}
