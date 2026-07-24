import {
  ArrowClockwiseIcon,
  DotsThreeIcon,
  GitForkIcon,
  LinkIcon,
  PencilSimpleIcon,
  PushPinIcon,
  XIcon,
} from "@phosphor-icons/react";
import {
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
import { CanvasFrameHost } from "@posthog/ui/features/canvas/freeform/CanvasFrameHost";
import { useCanvasFrameStore } from "@posthog/ui/features/canvas/freeform/canvasFrameStore";
import { CANVAS_QUERY_KEY } from "@posthog/ui/features/canvas/freeform/freeformDataBridge";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useChannelTasks } from "@posthog/ui/features/canvas/hooks/useChannelTasks";
import {
  useDashboard,
  useDashboardMutations,
} from "@posthog/ui/features/canvas/hooks/useDashboards";
import {
  useDashboardEditStore,
  useIsDashboardEditing,
} from "@posthog/ui/features/canvas/stores/dashboardEditStore";
import {
  useFreeformChatStore,
  useFreeformThread,
} from "@posthog/ui/features/canvas/stores/freeformChatStore";
import { copyCanvasLink } from "@posthog/ui/features/canvas/utils/copyCanvasLink";
import { TaskHeaderActions } from "@posthog/ui/features/task-detail/components/TaskHeaderActions";
import { useTasks } from "@posthog/ui/features/tasks/useTasks";
import { toast } from "@posthog/ui/primitives/toast";
import { track } from "@posthog/ui/shell/analytics";
import { useHeaderStore } from "@posthog/ui/shell/headerStore";
import { Box, Flex } from "@radix-ui/themes";
import { useQueryClient } from "@tanstack/react-query";
import {
  Outlet,
  useNavigate,
  useParams,
  useRouterState,
} from "@tanstack/react-router";
import type { ReactNode } from "react";

function threadIdFor(dashboardId: string): string {
  return `dashboard:${dashboardId}`;
}

// Edit toggle + autosave status + Fork for a canvas. Freeform
// autosaves every turn, so the toolbar shows a saving spinner rather than a Save
// button. When the user undoes to an older version, the autosave status is
// replaced by Revert (adopt the viewed version, dropping newer ones) + Cancel
// (jump back to the latest). Fork copies the current code to a new record.
function FreeformEditControls({
  channelId,
  dashboardId,
}: {
  channelId: string;
  dashboardId: string;
}) {
  const navigate = useNavigate();
  const editing = useIsDashboardEditing(dashboardId);
  const setEditing = useDashboardEditStore((s) => s.setEditing);
  const { dashboard } = useDashboard(dashboardId);
  const { forkFreeform, isCreating, setPinned } = useDashboardMutations();
  const isPinned = dashboard?.pinnedAt != null;

  const onTogglePin = () => {
    void setPinned(dashboardId, !isPinned)
      .then(() =>
        track(ANALYTICS_EVENTS.DASHBOARD_ACTION, {
          action_type: isPinned ? "unpin" : "pin",
          surface: "canvas",
          channel_id: channelId,
          dashboard_id: dashboardId,
          kind: "freeform",
          success: true,
        }),
      )
      .catch((error: unknown) => {
        track(ANALYTICS_EVENTS.DASHBOARD_ACTION, {
          action_type: isPinned ? "unpin" : "pin",
          surface: "canvas",
          channel_id: channelId,
          dashboard_id: dashboardId,
          kind: "freeform",
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

  const threadId = threadIdFor(dashboardId);
  const { code, versions, currentVersionId, isSaving } =
    useFreeformThread(threadId);
  const revert = useFreeformChatStore((s) => s.revert);
  const goToLatest = useFreeformChatStore((s) => s.goToLatest);

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
      kind: "freeform",
    });
    void queryClient.invalidateQueries({ queryKey: [CANVAS_QUERY_KEY] });
    remountFrame(dashboardId);
  };

  const hasCode = code.length > 0;
  // Viewing the head version (or there's no history yet) → autosave is live.
  // Otherwise the user has undone to an older version and is browsing.
  const onLatest =
    versions.length === 0 || currentVersionId === versions.at(-1)?.id;

  const onFork = async () => {
    if (!code) return;
    try {
      const name = `${dashboard?.name ?? "Canvas"} (fork)`;
      const record = await forkFreeform(
        channelId,
        name,
        code,
        versions,
        currentVersionId ?? undefined,
      );
      track(ANALYTICS_EVENTS.DASHBOARD_ACTION, {
        action_type: "fork",
        surface: "canvas",
        channel_id: channelId,
        dashboard_id: dashboardId,
        kind: "freeform",
        success: true,
      });
      setEditing(record.id, true);
      void navigate({
        to: "/website/$channelId/dashboards/$dashboardId",
        params: { channelId, dashboardId: record.id },
      });
    } catch (error) {
      track(ANALYTICS_EVENTS.DASHBOARD_ACTION, {
        action_type: "fork",
        surface: "canvas",
        channel_id: channelId,
        dashboard_id: dashboardId,
        kind: "freeform",
        success: false,
      });
      toast.error("Couldn't fork canvas", {
        description: error instanceof Error ? error.message : String(error),
      });
    }
  };

  return (
    <Flex align="center" gap="2" className="no-drag">
      {editing &&
        hasCode &&
        (onLatest ? (
          // Autosave status — a non-interactive button showing a spinner while a
          // save is in flight, "Saved" otherwise.
          <Button variant="outline" size="sm" disabled loading={isSaving}>
            Saved
          </Button>
        ) : (
          <>
            <Button
              variant="primary"
              size="sm"
              onClick={() => {
                track(ANALYTICS_EVENTS.DASHBOARD_ACTION, {
                  action_type: "revert",
                  surface: "canvas",
                  channel_id: channelId,
                  dashboard_id: dashboardId,
                  kind: "freeform",
                });
                revert(threadId);
              }}
            >
              Revert to this version
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => goToLatest(threadId)}
            >
              Cancel
            </Button>
          </>
        ))}
      {editing && (
        <Button
          variant="outline"
          size="sm"
          disabled={!hasCode || isCreating}
          onClick={onFork}
        >
          <GitForkIcon size={14} />
          Save as fork
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
        <DropdownMenuContent align="end" side="bottom" sideOffset={4}>
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
            {isPinned ? "Unpin from channel" : "Pin to channel"}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
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
            kind: "freeform",
            editing: !editing,
          });
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
  const { renameDashboard } = useDashboardMutations();
  const name = dashboard?.name ?? "Canvas";

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
      trailing={trailing}
    />
  );
}

// Canvas toolbar + content outlet for the Website space (channel-scoped). A
// single toolbar carries the channel breadcrumb (left) and data controls /
// actions (right).
export function WebsiteLayout() {
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const params = useParams({ strict: false });

  // App pages mirrored into the Channels space (Home, Skills, MCP servers,
  // Command Center) are channel-less and push their title into the shared
  // header store. With no code HeaderRow here, surface that title in this bar so
  // the mirrored pages read the same as in Code.
  const headerContent = useHeaderStore((s) => s.content);

  const channelId = params.channelId;
  const dashboardId = params.dashboardId;
  const taskId = params.taskId;
  const base = channelId ? `/website/${channelId}` : "/website";

  const { data: tasks } = useTasks();
  const { tasks: filedTasks } = useChannelTasks(channelId);
  const channelTask = filedTasks.some((record) => record.taskId === taskId)
    ? tasks?.find((task) => task.id === taskId)
    : undefined;

  const { channels } = useChannels();
  const channelName = channelId
    ? (channels.find((c) => c.id === channelId)?.name ?? "Channel")
    : "Channel";

  const isDashboardDetail = Boolean(channelId && dashboardId);
  // The canvases grid (its own sub-route now that the channel index is the
  // static homepage, which carries its own header content).
  const isDashboardsGrid =
    Boolean(channelId) && pathname === `${base}/canvases`;

  // Whether the single toolbar should render: the canvases grid, or any single
  // canvas (so Edit lives here too).
  const showToolbar =
    Boolean(channelId) && (isDashboardsGrid || isDashboardDetail);

  return (
    <Flex direction="column" height="100%" overflow="hidden">
      {/* Title bar for non-canvas views: every channel scene (task detail,
          new task, CONTEXT.md) pushes its "# channel / leaf" breadcrumb into
          the header store, as do channel-less mirrored pages (Home, Skills, …).
          Hidden when the canvas toolbar is showing (grid / a single canvas). */}
      {!showToolbar && headerContent && (
        <Flex
          align="center"
          gap="2"
          className="h-10 shrink-0 border-gray-6 border-b px-3"
        >
          <Flex
            align="center"
            justify="between"
            className="h-full min-w-0 flex-1 overflow-hidden"
          >
            {headerContent}
          </Flex>
          {channelTask && <TaskHeaderActions task={channelTask} />}
        </Flex>
      )}

      {/* Single canvas toolbar: the "# channel / canvas" breadcrumb (left) and
          canvas actions (Edit / Save as fork / New canvas) on the right.
          Freeform canvases own their own date control in-app (DateTimePicker). */}
      {showToolbar && channelId && (
        <Flex
          align="center"
          className="h-10 shrink-0 border-border border-b px-3"
        >
          {isDashboardDetail && dashboardId ? (
            <CanvasBreadcrumb
              channelName={channelName}
              channelId={channelId}
              dashboardId={dashboardId}
              trailing={
                <FreeformEditControls
                  channelId={channelId}
                  dashboardId={dashboardId}
                />
              }
            />
          ) : (
            <ChannelBreadcrumb
              channelName={channelName}
              channelId={channelId}
              leafLabel="Canvases"
              trailing={<NewCanvasMenu channelId={channelId} />}
            />
          )}
        </Flex>
      )}
      <Box flexGrow="1" overflow="hidden">
        <Outlet />
      </Box>
      {/* Warm-iframe pool for canvases. Mounted once here so it persists across
          every in-space navigation; overlays itself onto the active canvas's
          placeholder and stays warm-but-hidden otherwise. */}
      <CanvasFrameHost />
    </Flex>
  );
}
