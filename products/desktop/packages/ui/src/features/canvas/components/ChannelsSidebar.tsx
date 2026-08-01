import { ArchiveIcon } from "@phosphor-icons/react";
import { cn, Separator } from "@posthog/quill";
import { PROJECT_BLUEBIRD_FLAG } from "@posthog/shared";
import { useArchivedTaskIds } from "@posthog/ui/features/archive/useArchivedTaskIds";
import { ChannelNav } from "@posthog/ui/features/canvas/components/ChannelNav";
import { ChannelSidebar } from "@posthog/ui/features/canvas/components/ChannelSidebar";
import { ChannelsFab } from "@posthog/ui/features/canvas/components/ChannelsFab";
import { ChannelsList } from "@posthog/ui/features/canvas/components/ChannelsList";
import { useChannelsSidebarStore } from "@posthog/ui/features/canvas/components/channelsSidebarStore";
import { useChannelPaneSwipe } from "@posthog/ui/features/canvas/hooks/useChannelPaneSwipe";
import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import { useCurrentChannel } from "@posthog/ui/features/canvas/hooks/useCurrentChannel";
import { PERSONAL_CHANNEL_NAME } from "@posthog/ui/features/canvas/hooks/useTaskChannels";
import { useTrackChannelsSpaceViewed } from "@posthog/ui/features/canvas/hooks/useTrackChannelsSpaceViewed";
import {
  showChannelList,
  showChannelPane,
  useChannelPaneStore,
} from "@posthog/ui/features/canvas/stores/channelPaneStore";
import { useCurrentChannelStore } from "@posthog/ui/features/canvas/stores/currentChannelStore";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { LoopsPromoCard } from "@posthog/ui/features/loops/components/LoopsPromoCard";
import { useOnboardingStore } from "@posthog/ui/features/onboarding/onboardingStore";
import { ProjectSwitcher } from "@posthog/ui/features/sidebar/components/ProjectSwitcher";
import { SidebarMenu } from "@posthog/ui/features/sidebar/components/SidebarMenu";
import { SidebarNavSection } from "@posthog/ui/features/sidebar/components/SidebarNavSection";
import { TasksHeader } from "@posthog/ui/features/sidebar/components/TasksHeader";
import { UpdateBanner } from "@posthog/ui/features/sidebar/components/UpdateBanner";
import { CHANNELS_SIDEBAR_MIN_WIDTH } from "@posthog/ui/features/sidebar/constants";
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
import { Box, Flex } from "@radix-ui/themes";
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
}: {
  channelId: string | null;
  showList: boolean;
}) {
  const panesRef = useRef<HTMLDivElement | null>(null);
  useChannelPaneSwipe(panesRef, {
    // With no channel to slide to, the list is all there is — leave the gesture
    // to the platform rather than eat it for a slide that can't happen.
    enabled: channelId != null,
    onBack: showChannelList,
    onForward: showChannelPane,
  });

  return (
    <Box ref={panesRef} className="min-h-0 flex-1 overflow-hidden">
      <div
        className={cn(
          "flex h-full w-[200%] transition-transform duration-200 ease-out motion-reduce:transition-none",
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
    </Box>
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

  const peek = useSidebarPeekStore((s) => s.peek);
  useSidebarEdgeHoverPeek({
    enabled: !open && !isResizing,
    peeked: peek,
    side: "left",
    width,
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
  const bluebirdEnabled = useFeatureFlag(
    PROJECT_BLUEBIRD_FLAG,
    import.meta.env.DEV,
  );
  const channelsEnabled =
    useSidebarStore((s) => s.channelsEnabled) && bluebirdEnabled;
  const channelsLayout = useChannelsLayout();
  const channelsWorld = channelsLayout || channelsEnabled;
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

  const params = useParams({ strict: false });
  const routeChannelId = params.channelId;
  const setCurrentChannel = useCurrentChannelStore((s) => s.setCurrentChannel);
  const { currentChannelId, channels } = useCurrentChannel({
    enabled: channelsLayout,
  });
  useEffect(() => {
    if (!channelsLayout || !routeChannelId) return;
    setCurrentChannel(routeChannelId);
    // Landing on a channel — a deep link, a mention, ⌘1-9 — is a request to see
    // it, so the slider follows the route even if the list was being browsed.
    showChannelPane();
  }, [channelsLayout, routeChannelId, setCurrentChannel]);

  // Browsing the list is view state, not navigation: you stay in the channel
  // (route and main pane unchanged) while you look around. With no channel to
  // slide to there's only the list.
  const pane = useChannelPaneStore((s) => s.pane);
  const showList = pane === "list" || currentChannelId == null;

  const autoScopedRef = useRef(false);
  useEffect(() => {
    if (!channelsLayout) {
      autoScopedRef.current = false;
      return;
    }
    // A route-scoped channel wins over the default. Both effects run from the
    // same render on a cold deep link, so without this guard the route effect
    // writes its channel and this later effect immediately overwrites it with
    // #me using the stale `currentChannelId` captured by that render.
    if (routeChannelId || autoScopedRef.current || currentChannelId) return;
    const me = channels.find((c) => c.name === PERSONAL_CHANNEL_NAME);
    if (!me) return;
    autoScopedRef.current = true;
    setCurrentChannel(me.id);
  }, [
    channelsLayout,
    channels,
    currentChannelId,
    routeChannelId,
    setCurrentChannel,
  ]);

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
    >
      <Flex direction="column" className="h-full bg-chrome">
        {!channelsLayout && (
          <>
            <SidebarNavSection />
            <TasksHeader />
          </>
        )}

        {channelsLayout ? (
          <>
            {/* Which project you're in is the outermost thing about this window,
                so under the layout it sits above the nav row rather than in the
                footer. Its menu opens downward, which is the right direction
                from the top of a sidebar. */}
            <Box className="shrink-0 px-2 pb-1">
              <ProjectSwitcher />
            </Box>
            <ChannelNav />
            <ChannelPanes channelId={currentChannelId} showList={showList} />
          </>
        ) : bodyChannelsWorld ? (
          <>
            <Separator />
            <Box className="relative min-h-0 flex-1">
              <ChannelsList />
              <ChannelsFab />
            </Box>
          </>
        ) : (
          <Box className="min-h-0 flex-1">
            <SidebarMenu />
          </Box>
        )}

        <UpdateBanner />

        {showArchivedRow && archivedTaskIds.size > 0 && (
          <Box className="shrink-0 border-border border-t">
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
          </Box>
        )}

        <LoopsPromoCard />

        {/* The code layout keeps it in the footer: that sidebar's top is the nav
            section and task header, and there's no nav row to sit above. */}
        {!channelsLayout && (
          <Box className="shrink-0 px-2 pb-2">
            <ProjectSwitcher />
          </Box>
        )}
      </Flex>
    </ResizableSidebar>
  );
}
