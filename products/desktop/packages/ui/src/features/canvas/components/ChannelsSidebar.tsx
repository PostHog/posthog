import { ArchiveIcon } from "@phosphor-icons/react";
import { Separator } from "@posthog/quill";
import { PROJECT_BLUEBIRD_FLAG } from "@posthog/shared";
import { useArchivedTaskIds } from "@posthog/ui/features/archive/useArchivedTaskIds";
import { ChannelsFab } from "@posthog/ui/features/canvas/components/ChannelsFab";
import { ChannelsList } from "@posthog/ui/features/canvas/components/ChannelsList";
import { useChannelsSidebarStore } from "@posthog/ui/features/canvas/components/channelsSidebarStore";
import { SpacesSidebarNav } from "@posthog/ui/features/canvas/components/SpacesSidebarNav";
import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import { useTrackChannelsSpaceViewed } from "@posthog/ui/features/canvas/hooks/useTrackChannelsSpaceViewed";
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
import { useSidebarEdgeHoverPeek } from "@posthog/ui/primitives/hooks/useSidebarEdgeHoverPeek";
import { ResizableSidebar } from "@posthog/ui/primitives/ResizableSidebar";
import { navigateToArchived } from "@posthog/ui/router/navigationBridge";
import { Box, Flex } from "@radix-ui/themes";
import { useDeferredValue, useEffect } from "react";

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
            {/* The static spaces sidebar (prototype): one nav where every space
                expands inline with its tasks beneath it. Replaces the panes
                slider under this flag. */}
            <Box className="min-h-0 flex-1 overflow-y-auto">
              <SpacesSidebarNav />
            </Box>
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
