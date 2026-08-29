import {
  ArrowClockwiseIcon,
  ChatCircleIcon,
  DotsThreeIcon,
  LinkIcon,
  PencilSimpleIcon,
  PushPinIcon,
  TrashIcon,
  XIcon,
} from "@phosphor-icons/react";
import { useHostTRPC } from "@posthog/host-router/react";
import {
  AlertDialog,
  AlertDialogClose,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { ChannelBreadcrumb } from "@posthog/ui/features/canvas/components/ChannelBreadcrumb";
import { iconForTemplate } from "@posthog/ui/features/canvas/components/canvasTemplateIcon";
import { NewCanvasMenu } from "@posthog/ui/features/canvas/components/NewCanvasMenu";
import { SpaceHeaderRow } from "@posthog/ui/features/canvas/components/SpaceHeaderRow";
import { deleteCanvasWithUndo } from "@posthog/ui/features/canvas/deleteCanvasWithUndo";
import { CanvasFrameHost } from "@posthog/ui/features/canvas/freeform/CanvasFrameHost";
import { canvasCommentTaskId } from "@posthog/ui/features/canvas/freeform/canvasCommentTask";
import { useCanvasFrameStore } from "@posthog/ui/features/canvas/freeform/canvasFrameStore";
import { CANVAS_QUERY_KEY } from "@posthog/ui/features/canvas/freeform/freeformDataBridge";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import { useChannelTasks } from "@posthog/ui/features/canvas/hooks/useChannelTasks";
import {
  useCanvasVersions,
  useDashboard,
  useDashboardMutations,
} from "@posthog/ui/features/canvas/hooks/useDashboards";
import { useSelectedCanvasId } from "@posthog/ui/features/canvas/hooks/useSelectedCanvasId";
import { useCanvasChatPanelStore } from "@posthog/ui/features/canvas/stores/canvasChatPanelStore";
import {
  useDashboardEditStore,
  useIsDashboardEditing,
} from "@posthog/ui/features/canvas/stores/dashboardEditStore";
import { copyCanvasLink } from "@posthog/ui/features/canvas/utils/copyCanvasLink";
import { RightPanel } from "@posthog/ui/features/navigation/components/RightPanel";
import {
  CONTENT_CHROME_RIGHT_VAR,
  SWITCHER_WIDTH_PX,
  useRightPanelOpen,
} from "@posthog/ui/features/navigation/rightPanelSide";
import { useActiveSession } from "@posthog/ui/features/navigation/useActiveSession";
import { buildCommentThreads } from "@posthog/ui/features/sessions/components/commentViewTypes";
import { useCommentsQuery } from "@posthog/ui/features/sessions/components/useComments";
import {
  MentionAvailabilityProvider,
  PRIVATE_SPACE_MENTIONS_DISABLED,
} from "@posthog/ui/features/sessions/mentionAvailability";
import { useTasks } from "@posthog/ui/features/tasks/useTasks";
import { toast } from "@posthog/ui/primitives/toast";
import { track } from "@posthog/ui/shell/analytics";
import { Flex } from "@radix-ui/themes";
import { useIsMutating, useQueryClient } from "@tanstack/react-query";
import {
  Outlet,
  useNavigate,
  useParams,
  useRouterState,
} from "@tanstack/react-router";
import { type CSSProperties, type ReactNode, useState } from "react";

// Edit toggle + autosave status for a canvas. Source is server-versioned now —
// version browsing and revert live in the canvas view's own toolbar — so the
// only autosave surfaced here is the author-context buffer's saveContext.
function FreeformEditControls({
  channelId,
  dashboardId,
}: {
  channelId: string;
  dashboardId: string;
}) {
  const navigate = useNavigate();
  // Pinning is scoped to whatever holds the canvas; the new layout calls that a
  // space, the old one a channel.
  const spacesLayout = useChannelsLayout();
  const containerNoun = spacesLayout ? "space" : "channel";
  const editing = useIsDashboardEditing(dashboardId);
  const setEditing = useDashboardEditStore((s) => s.setEditing);
  const openChat = useCanvasChatPanelStore((state) => state.openChat);
  const { dashboard } = useDashboard(dashboardId);
  const { setPinned, invalidateDashboards } = useDashboardMutations();
  const isPinned = dashboard?.pinnedAt != null;
  // "Delete…" opens a confirmation rather than deleting inline — the canvas and
  // its version history go away for everyone in the space.
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);

  // Once confirmed the canvas vanishes from every list and we return to the
  // space, but the delete isn't sent until the undo toast's
  // timer runs out — Undo simply cancels it.
  const confirmDelete = () => {
    setConfirmDeleteOpen(false);
    deleteCanvasWithUndo({
      dashboardId,
      channelId,
      name: dashboard?.name ?? "Canvas",
      surface: "canvas",
      invalidate: invalidateDashboards,
    });
    void navigate({
      to: "/spaces/$channelId",
      params: { channelId },
    });
  };

  const onTogglePin = () => {
    void setPinned(dashboardId, !isPinned)
      .then(() =>
        track(ANALYTICS_EVENTS.DASHBOARD_ACTION, {
          action_type: isPinned ? "unpin" : "pin",
          surface: "canvas",
          channel_id: channelId,
          dashboard_id: dashboardId,
          success: true,
        }),
      )
      .catch((error: unknown) => {
        track(ANALYTICS_EVENTS.DASHBOARD_ACTION, {
          action_type: isPinned ? "unpin" : "pin",
          surface: "canvas",
          channel_id: channelId,
          dashboard_id: dashboardId,
          success: false,
        });
        toast.error(
          isPinned ? "Couldn't unpin canvas" : "Couldn't pin canvas",
          {
            description: error instanceof Error ? error.message : String(error),
          },
        );
      });
  };

  // Any in-flight saveContext mutation (the side panel's context editor
  // commits through it) drives the toolbar's autosave spinner.
  const trpc = useHostTRPC();
  const isSavingContext =
    useIsMutating({
      mutationKey: trpc.dashboards.saveContext.mutationKey(),
    }) > 0;

  const queryClient = useQueryClient();
  const remountFrame = useCanvasFrameStore((s) => s.remount);
  // Fully remount the mounted canvas iframe: drop the host-side read cache so
  // queries re-run, then recreate the iframe element (not just reload its
  // document) so a refresh also recovers from a wedged frame.
  const onRefresh = () => {
    track(ANALYTICS_EVENTS.DASHBOARD_ACTION, {
      action_type: "refresh",
      surface: "canvas",
      channel_id: channelId,
      dashboard_id: dashboardId,
    });
    void queryClient.invalidateQueries({ queryKey: [CANVAS_QUERY_KEY] });
    remountFrame(dashboardId);
  };

  return (
    <Flex align="center" gap="2" className="no-drag">
      {editing && (
        // Autosave status — a non-interactive button showing a spinner while a
        // context save is in flight, "Saved" otherwise.
        <Button variant="outline" size="sm" disabled loading={isSavingContext}>
          Saved
        </Button>
      )}
      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <Button
              variant="outline"
              size="icon-sm"
              aria-label="Canvas options"
            >
              <DotsThreeIcon size={16} weight="bold" />
            </Button>
          }
        />
        {/* Sized to its longest item — the default width clipped "Unpin from
            space". Same treatment as the channel-list menus. */}
        <DropdownMenuContent
          align="end"
          side="bottom"
          sideOffset={4}
          className="w-auto min-w-fit"
        >
          <DropdownMenuItem onClick={onRefresh}>
            <ArrowClockwiseIcon size={14} />
            Refresh
          </DropdownMenuItem>
          <DropdownMenuItem
            onClick={() =>
              void copyCanvasLink(channelId, dashboardId, "canvas")
            }
          >
            <LinkIcon size={14} />
            Copy link
          </DropdownMenuItem>
          <DropdownMenuItem onClick={onTogglePin}>
            <PushPinIcon size={14} weight={isPinned ? "fill" : "regular"} />
            {isPinned
              ? `Unpin from ${containerNoun}`
              : `Pin to ${containerNoun}`}
          </DropdownMenuItem>
          <DropdownMenuItem
            variant="destructive"
            onClick={() => setConfirmDeleteOpen(true)}
          >
            <TrashIcon size={14} />
            Delete…
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      {/* Destructive confirm for "Delete…" — the canvas goes for everyone. */}
      <AlertDialog open={confirmDeleteOpen} onOpenChange={setConfirmDeleteOpen}>
        <AlertDialogContent className="max-w-md">
          <AlertDialogHeader>
            <AlertDialogTitle>Delete canvas</AlertDialogTitle>
            <AlertDialogDescription>
              Delete{" "}
              <span className="font-medium">{dashboard?.name ?? "Canvas"}</span>
              ? Its code and version history go for everyone in the{" "}
              {containerNoun}. You get a few seconds to undo, then it's
              permanent.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogClose
              render={
                <Button variant="outline" size="sm">
                  Cancel
                </Button>
              }
            />
            <Button variant="destructive" size="sm" onClick={confirmDelete}>
              Delete
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      <Button
        variant="outline"
        size="sm"
        data-selected={editing}
        onClick={() => {
          track(ANALYTICS_EVENTS.DASHBOARD_ACTION, {
            action_type: "edit_toggle",
            surface: "canvas",
            channel_id: channelId,
            dashboard_id: dashboardId,
            editing: !editing,
          });
          if (!editing) openChat();
          setEditing(dashboardId, !editing);
        }}
      >
        {editing ? (
          <XIcon size={14} />
        ) : (
          <PencilSimpleIcon size={14} weight="regular" />
        )}
        {editing ? "Done" : "Edit"}
      </Button>
    </Flex>
  );
}

// "# channel / canvas" breadcrumb for a single canvas, with the leaf inline-
// renamable and a tier icon (dashboard / web-analytics / freeform app).
function CanvasBreadcrumb({
  channelName,
  channelId,
  dashboardId,
  trailing,
}: {
  channelName: string;
  channelId: string;
  dashboardId: string;
  trailing?: ReactNode;
}) {
  const { dashboard } = useDashboard(dashboardId);
  const { versions } = useCanvasVersions(dashboardId);
  const { renameDashboard } = useDashboardMutations();
  const openComments = useCanvasChatPanelStore((state) => state.openComments);
  const name = dashboard?.name ?? "Canvas";
  const commentTarget = {
    scope: "desktop_canvas" as const,
    itemId: dashboardId,
  };
  const commentTaskId = canvasCommentTaskId(
    dashboard?.generationTaskId,
    versions,
  );
  const comments = useCommentsQuery(
    commentTaskId ? commentTarget : null,
    commentTaskId ?? "",
    { live: true },
  );
  const openCommentCount = buildCommentThreads(comments.data ?? []).filter(
    (thread) => !thread.resolved,
  ).length;

  return (
    <ChannelBreadcrumb
      channelName={channelName}
      channelId={channelId}
      leafIcon={iconForTemplate(dashboard?.templateId ?? "", {
        size: 12,
        // No color here: the breadcrumb's leaf <span> owns the icon color so it
        // can be styled in one place.
        className: "",
      })}
      leafLabel={name}
      editScopeKey={dashboardId}
      onRename={(next) => void renameDashboard(dashboardId, next)}
      trailing={
        <>
          {commentTaskId && (
            <Button size="sm" variant="outline" onClick={openComments}>
              <ChatCircleIcon />
              Comments
              {openCommentCount > 0 && (
                <span className="tabular-nums">{openCommentCount}</span>
              )}
            </Button>
          )}
          {trailing}
        </>
      }
    />
  );
}

export function ShellLayout() {
  const spacesLayout = useChannelsLayout();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const selectedCanvasId = useSelectedCanvasId();
  const params = useParams({ strict: false });

  const channelId = params.channelId;
  const dashboardId = params.dashboardId;
  const { dashboard: selectedCanvas } = useDashboard(selectedCanvasId);
  const toolbarDashboardId = dashboardId ?? selectedCanvasId;
  const toolbarChannelId = channelId ?? selectedCanvas?.channelId;

  // Activity reads a task into its pane off the feed, so the session is not
  // always the one in the URL.
  const { taskId, channelId: taskChannelId } = useActiveSession();

  const rightPanelOpen = useRightPanelOpen(taskId);
  const base = channelId ? `/spaces/${channelId}` : "/spaces";

  const { data: tasks } = useTasks();
  const { tasks: filedTasks } = useChannelTasks(taskChannelId);
  const channelTask = filedTasks.some((record) => record.taskId === taskId)
    ? tasks?.find((task) => task.id === taskId)
    : undefined;

  const { channels } = useChannels();
  const mentionsDisabledReason =
    channels.find((channel) => channel.id === taskChannelId)?.channelType ===
    "personal"
      ? PRIVATE_SPACE_MENTIONS_DISABLED
      : null;
  const channelName = channelId
    ? (channels.find((c) => c.id === channelId)?.name ??
      (spacesLayout ? "Space" : "Channel"))
    : spacesLayout
      ? "Space"
      : "Channel";
  const toolbarChannelName = toolbarChannelId
    ? (channels.find((c) => c.id === toolbarChannelId)?.name ?? channelName)
    : channelName;

  const isDashboardDetail = Boolean(toolbarDashboardId);
  // The canvases grid (its own sub-route now that the channel index is the
  // static homepage, which carries its own header content).
  const isDashboardsGrid =
    Boolean(channelId) && pathname === `${base}/canvases`;

  // Whether the single toolbar should render: the canvases grid, or any single
  // canvas (so Edit lives here too).
  const showToolbar = isDashboardsGrid || isDashboardDetail;

  return (
    <Flex direction="column" height="100%" overflow="hidden">
      {/* Title bar for non-canvas views: every channel scene (task detail,
          new task, CONTEXT.md) pushes its "# channel / leaf" breadcrumb into
          the header store, as do channel-less mirrored pages (Home, Skills, …).
          Hidden when the canvas toolbar is showing (grid / a single canvas),
          and skipped entirely when there is neither a title nor a session's
          actions to carry. */}
      {!showToolbar && <SpaceHeaderRow task={channelTask} />}

      {/* Single canvas toolbar: the "# channel / canvas" breadcrumb (left) and
          canvas actions (Edit / New canvas) on the right.
          Freeform canvases own their own date control in-app (DateTimePicker). */}
      {showToolbar && (
        <div className="flex h-10 shrink-0 items-center border-border border-b px-3">
          {isDashboardDetail && toolbarDashboardId && toolbarChannelId ? (
            <CanvasBreadcrumb
              channelName={toolbarChannelName}
              channelId={toolbarChannelId}
              dashboardId={toolbarDashboardId}
              trailing={
                <FreeformEditControls
                  channelId={toolbarChannelId}
                  dashboardId={toolbarDashboardId}
                />
              }
            />
          ) : channelId ? (
            <ChannelBreadcrumb
              channelName={channelName}
              channelId={channelId}
              leafLabel="Canvases"
              trailing={<NewCanvasMenu channelId={channelId} />}
            />
          ) : null}
        </div>
      )}
      {/* The right panel lays itself over this row's right edge and pins its
          switcher to the row's top right, so the row is its positioning context
          and its ceiling - the panel never reaches over the nav beside it.
          `isolate` keeps the switcher's stacking rank inside the row, where it
          only has to beat the panel's own layer, rather than reaching the app's
          dialogs and popovers. While the panel is closed the switcher floats
          over the content pane, so the row publishes how much of its right edge
          is spoken for and the pane's own chrome stops short of it. */}
      <div
        className="relative isolate flex min-h-0 flex-1 overflow-hidden"
        style={
          {
            [CONTENT_CHROME_RIGHT_VAR]: rightPanelOpen
              ? "0px"
              : `${SWITCHER_WIDTH_PX}px`,
          } as CSSProperties
        }
      >
        {/* `isolate`: the pane's own chrome climbs to z-50, and without a
            stacking context of its own that would outrank the right panel's
            scrim, which has to sit under the panel and so cannot simply outbid
            it. */}
        <div className="isolate min-w-0 flex-1 overflow-hidden">
          <MentionAvailabilityProvider disabledReason={mentionsDisabledReason}>
            <Outlet />
          </MentionAvailabilityProvider>
        </div>
        {/* One panel at a time at the right of the content: the session's
            timeline, artifacts, comments, or changes. */}
        {spacesLayout && <RightPanel />}
      </div>
      {/* Warm-iframe pool for canvases. Mounted once here so it persists across
          every in-space navigation; overlays itself onto the active canvas's
          placeholder and stays warm-but-hidden otherwise. */}
      <CanvasFrameHost />
    </Flex>
  );
}
