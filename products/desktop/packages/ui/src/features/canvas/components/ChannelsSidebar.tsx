import { ArchiveIcon } from "@phosphor-icons/react";
import { cn, Separator } from "@posthog/quill";
import { useArchivedTaskIds } from "@posthog/ui/features/archive/useArchivedTaskIds";
import { usePendingTabViewState } from "@posthog/ui/features/browser-tabs/usePendingTabViewState";
import { ActivityFeedList } from "@posthog/ui/features/canvas/components/ActivityFeedList";
import { CanvasesPane } from "@posthog/ui/features/canvas/components/CanvasesPane";
import { ChannelItemPreviewCardProvider } from "@posthog/ui/features/canvas/components/ChannelItemHoverCard";
import { ChannelSidebar } from "@posthog/ui/features/canvas/components/ChannelSidebar";
import { ChannelsFab } from "@posthog/ui/features/canvas/components/ChannelsFab";
import { ChannelsList } from "@posthog/ui/features/canvas/components/ChannelsList";
import { useChannelsSidebarStore } from "@posthog/ui/features/canvas/components/channelsSidebarStore";
import { TaskFeedPane } from "@posthog/ui/features/canvas/components/TaskFeedPane";
import { useChannelPaneSwipe } from "@posthog/ui/features/canvas/hooks/useChannelPaneSwipe";
import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import { useChannelsWorld } from "@posthog/ui/features/canvas/hooks/useChannelsWorld";
import { useCurrentChannel } from "@posthog/ui/features/canvas/hooks/useCurrentChannel";
import { useMarkChannelSeen } from "@posthog/ui/features/canvas/hooks/useMarkChannelSeen";
import { useRailSurface } from "@posthog/ui/features/canvas/hooks/useRailSurface";
import { useTrackChannelsSpaceViewed } from "@posthog/ui/features/canvas/hooks/useTrackChannelsSpaceViewed";
import {
  selectActivityItem,
  selectActivityReport,
  useActivitySelection,
} from "@posthog/ui/features/canvas/stores/activityDetailStore";
import {
  showChannelList,
  showChannelPane,
  useChannelPaneStore,
} from "@posthog/ui/features/canvas/stores/channelPaneStore";
import { useOnboardingStore } from "@posthog/ui/features/onboarding/onboardingStore";
import { NavResizeTooltip } from "@posthog/ui/features/sidebar/components/NavResizeTooltip";
import { ProjectSwitcher } from "@posthog/ui/features/sidebar/components/ProjectSwitcher";
import { SidebarMenu } from "@posthog/ui/features/sidebar/components/SidebarMenu";
import { SidebarNavSection } from "@posthog/ui/features/sidebar/components/SidebarNavSection";
import { TasksHeader } from "@posthog/ui/features/sidebar/components/TasksHeader";
import { UpdateBanner } from "@posthog/ui/features/sidebar/components/UpdateBanner";
import {
  CHANNELS_SIDEBAR_MIN_WIDTH,
  NAV_RAIL_WIDTH,
} from "@posthog/ui/features/sidebar/constants";
import {
  beginSidebarPeek,
  cancelSidebarPeek,
  endSidebarPeek,
  useSidebarPeekStore,
} from "@posthog/ui/features/sidebar/sidebarPeekStore";
import { useSidebarStore } from "@posthog/ui/features/sidebar/sidebarStore";
import { useWorkspaces } from "@posthog/ui/features/workspace/useWorkspace";
import { ErrorBoundary } from "@posthog/ui/primitives/ErrorBoundary";
import { useSidebarEdgeHoverPeek } from "@posthog/ui/primitives/hooks/useSidebarEdgeHoverPeek";
import { ResizableSidebar } from "@posthog/ui/primitives/ResizableSidebar";
import { navigateToArchived } from "@posthog/ui/router/navigationBridge";
import { useParams } from "@tanstack/react-router";
import { useDeferredValue, useEffect, useRef } from "react";

/**
 * The sidebar slider: the channel list and the channel you're in, laid out side
 * by side in a track that translates between them.
 *
 * Both panes stay mounted so the slide has something to slide, and so coming
 * back to the list doesn't rebuild every row's menus and dialogs. The offscreen
 * one is `inert`, keeping it out of the tab order and off screen readers.
 *
 * A two-finger horizontal swipe moves between them, so the back row isn't the
 * only way out of a channel — and swiping the other way returns to the channel
 * that stayed scoped the whole time.
 */
function ChannelPanes({
  channelId,
  showList,
  sidebarVisible,
  pendingTabSwitch,
}: {
  channelId: string | null;
  showList: boolean;
  sidebarVisible: boolean;
  pendingTabSwitch: boolean;
}) {
  // Mark the channel seen only while a reader can see its pane: this pane is
  // the one showing (not the list) and the sidebar is on screen. A collapsed
  // sidebar keeps both panes mounted, so without the visibility gate a mention
  // landing behind it would clear the unread emphasis nobody saw.
  const visibleChannelId =
    !pendingTabSwitch && !showList && sidebarVisible
      ? (channelId ?? undefined)
      : undefined;
  useMarkChannelSeen(visibleChannelId);
  const animateTransition = useChannelPaneStore(
    (state) => state.animateTransition,
  );
  const finishTransition = useChannelPaneStore(
    (state) => state.finishTransition,
  );
  const panesRef = useRef<HTMLDivElement | null>(null);
  useChannelPaneSwipe(panesRef, {
    // With no channel to slide to, the list is all there is — leave the gesture
    // to the platform rather than eat it for a slide that can't happen.
    enabled: channelId != null,
    onBack: showChannelList,
    onForward: showChannelPane,
  });

  return (
    <div ref={panesRef} className="min-h-0 flex-1 overflow-hidden">
      <div
        onTransitionEnd={(event) => {
          if (event.currentTarget === event.target) finishTransition();
        }}
        className={cn(
          "flex h-full w-[200%]",
          animateTransition &&
            "transition-transform duration-200 ease-out motion-reduce:transition-none",
          showList ? "translate-x-0" : "-translate-x-1/2",
        )}
      >
        <div className="relative h-full w-1/2 min-w-0" inert={!showList}>
          <ChannelsList />
          <ChannelsFab />
        </div>
        <div className="h-full w-1/2 min-w-0" inert={showList}>
          {channelId && (
            <ErrorBoundary
              name="channel-sidebar"
              fallback={<ChannelsList />}
              resetKey={channelId}
            >
              <ChannelSidebar channelId={channelId} />
            </ErrorBoundary>
          )}
        </div>
      </div>
    </div>
  );
}
export function ChannelsSidebar() {
  const width = useChannelsSidebarStore((state) => state.width);
  const setWidth = useChannelsSidebarStore((state) => state.setWidth);
  const isResizing = useChannelsSidebarStore((state) => state.isResizing);
  const setIsResizing = useChannelsSidebarStore((state) => state.setIsResizing);

  // Cmd+B collapses the sidebar (via useSidebarStore.open, toggled globally in
  // GlobalEventHandlers / the command menu). Auto-open once the user has
  // finished onboarding or has any workspace, matching the retired MainSidebar —
  // so a brand-new user sees the welcome screen without the sidebar beside it.
  const open = useSidebarStore((s) => s.open);
  const setOpen = useSidebarStore((s) => s.setOpen);
  const setOpenAuto = useSidebarStore((s) => s.setOpenAuto);
  const hasCompletedOnboarding = useOnboardingStore(
    (s) => s.hasCompletedOnboarding,
  );
  const { data: workspaces = {}, isFetched: workspacesFetched } =
    useWorkspaces();
  useEffect(() => {
    if (!workspacesFetched) return;
    setOpenAuto(hasCompletedOnboarding || Object.keys(workspaces).length > 0);
  }, [workspacesFetched, workspaces, hasCompletedOnboarding, setOpenAuto]);

  const channelsLayout = useChannelsLayout();
  const peek = useSidebarPeekStore((s) => s.peek);
  useSidebarEdgeHoverPeek({
    enabled: !open && !isResizing,
    peeked: peek,
    side: "left",
    width,
    // Hovering a rail button is not a request to slide the sidebar out.
    offset: channelsLayout ? NAV_RAIL_WIDTH : 0,
    onReveal: beginSidebarPeek,
    onClose: () => endSidebarPeek(),
  });
  useEffect(() => {
    if (open) cancelSidebarPeek();
  }, [open]);
  // The peek store is a module-level singleton — if this sidebar unmounts
  // while peeked (route without it), a stale peek would greet the remount.
  useEffect(() => () => cancelSidebarPeek(), []);

  // Channels stay behind project-bluebird: the switch only appears where the
  // canvas backend is wired, and a persisted "on" is ignored when the flag is
  // off so the sidebar can't strand a user on an unsupported feature.
  const channelsWorld = useChannelsWorld();
  const bodyChannelsWorld = useDeferredValue(channelsWorld);
  // Under the layout the row moves into the account menu (ProjectSwitcher),
  // beside Settings — the bottom of the sidebar belongs to the channel list.
  const showArchivedRow = !channelsLayout && !bodyChannelsWorld;
  useTrackChannelsSpaceViewed({
    enabled: channelsWorld,
    layout: channelsLayout ? "channels" : "code",
  });

  const minWidth = channelsLayout ? CHANNELS_SIDEBAR_MIN_WIDTH : undefined;
  useEffect(() => {
    if (channelsLayout && width < CHANNELS_SIDEBAR_MIN_WIDTH) {
      setWidth(CHANNELS_SIDEBAR_MIN_WIDTH);
    }
  }, [channelsLayout, width, setWidth]);

  const archivedTaskIds = useArchivedTaskIds();

  // Scoping lives in ChannelRouteSync: this column is not always drawn.
  const { currentChannelId } = useCurrentChannel({ enabled: channelsLayout });

  // Browsing the list is view state, not navigation: you stay in the channel
  // (route and main pane unchanged) while you look around. With no channel to
  // slide to there's only the list.
  const { pane: railPane, showsActivityDetail } = useRailSurface();
  const selectedActivityId = useActivitySelection()?.id;
  const { feedId } = useParams({ strict: false });
  const pane = useChannelPaneStore((s) => s.pane);
  const { isPending: pendingTabSwitch, viewState: pendingTabViewState } =
    usePendingTabViewState();
  const presentedChannelId =
    pendingTabViewState?.spaceId !== undefined
      ? pendingTabViewState.spaceId
      : currentChannelId;
  const showList =
    (pendingTabViewState?.listOpen ?? pane === "list") ||
    presentedChannelId == null;

  return (
    <ResizableSidebar
      open={open}
      width={width}
      setWidth={setWidth}
      isResizing={isResizing}
      setIsResizing={setIsResizing}
      side="left"
      minWidth={minWidth}
      setOpen={setOpen}
      peek={peek}
      onPeekEnter={beginSidebarPeek}
      onPeekLeave={() => endSidebarPeek()}
      onPeekDismiss={cancelSidebarPeek}
      resizeTooltip={<NavResizeTooltip />}
      drawEdge={!channelsLayout}
    >
      {/* One preview card for every row in here — the channel's own list and
          the space tree both draw their rows as triggers on it. */}
      <ChannelItemPreviewCardProvider>
        <div
          className={cn(
            "flex h-full flex-col bg-chrome",
            // This column starts the framed inset, so it owns the whole
            // outline: a second owner of any edge doubles that line.
            channelsLayout &&
              "rounded-tl-lg border-border border-t border-r border-l",
          )}
        >
          {!channelsLayout && (
            <>
              <SidebarNavSection />
              <TasksHeader />
            </>
          )}

          {channelsLayout ? (
            showsActivityDetail ? (
              <ActivityFeedList
                className="min-h-0 flex-1"
                selectedId={selectedActivityId}
                onActivate={selectActivityItem}
                onReportActivate={selectActivityReport}
              />
            ) : railPane === "canvases" ? (
              <CanvasesPane className="min-h-0 flex-1" />
            ) : feedId ? (
              <TaskFeedPane feedId={feedId} className="min-h-0 flex-1" />
            ) : (
              <ChannelPanes
                channelId={presentedChannelId}
                showList={showList}
                sidebarVisible={open || peek}
                pendingTabSwitch={pendingTabSwitch}
              />
            )
          ) : bodyChannelsWorld ? (
            <>
              <Separator />
              <div className="relative min-h-0 flex-1">
                <ChannelsList />
                <ChannelsFab />
              </div>
            </>
          ) : (
            <div className="min-h-0 flex-1">
              <SidebarMenu />
            </div>
          )}

          <UpdateBanner />

          {showArchivedRow && archivedTaskIds.size > 0 && (
            <div className="shrink-0 border-border border-t">
              <button
                type="button"
                className="flex w-full items-center gap-1 bg-transparent px-2 py-1.5 text-left text-[13px] text-gray-11 transition-colors hover:bg-gray-3"
                onClick={navigateToArchived}
              >
                <span className="flex h-[18px] w-[18px] shrink-0 items-center justify-center text-gray-10">
                  <ArchiveIcon size={14} />
                </span>
                <span className="text-gray-11">Archived</span>
              </button>
            </div>
          )}

          {/* The code layout keeps it in the footer: that sidebar's top is the nav
            section and task header, and there's no nav row to sit above. */}
          {!channelsLayout && (
            <div className="shrink-0 px-2 pb-2">
              <ProjectSwitcher />
            </div>
          )}
        </div>
      </ChannelItemPreviewCardProvider>
    </ResizableSidebar>
  );
}
