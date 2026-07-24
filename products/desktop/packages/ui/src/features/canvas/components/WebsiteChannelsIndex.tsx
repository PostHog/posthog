import { PlusIcon } from "@phosphor-icons/react";
import { Button } from "@posthog/quill";
import { BlankTabView } from "@posthog/ui/features/browser-tabs/BlankTabView";
import {
  useActiveTabIsBlank,
  usePrimaryWindowHasNoTabs,
} from "@posthog/ui/features/browser-tabs/useBrowserTabs";
import { CreateChannelModal } from "@posthog/ui/features/canvas/components/CreateChannelModal";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { Flex, Text } from "@radix-ui/themes";
import { Navigate, useRouterState } from "@tanstack/react-router";
import { useState } from "react";

// /website index: send the user to their first channel, or prompt them to
// create one when none exist yet.
export function WebsiteChannelsIndex() {
  const { channels, isLoading } = useChannels();
  const [modalOpen, setModalOpen] = useState(false);
  // A blank "+" tab parks at /website; RootLayout renders the placeholder for
  // it. Never redirect to the first channel while it's active.
  const activeTabIsBlank = useActiveTabIsBlank();
  // The user closed every tab — show the new-tab screen instead of redirecting
  // to the first channel, which would silently re-open a tab (the index's
  // redirect puts a channel in the route, and decideTabNavigation then opens a
  // tab for it). The empty strip should land on the new-tab screen.
  const hasNoTabs = usePrimaryWindowHasNoTabs();
  // Guard against TanStack rendering this stale index for a couple of frames
  // after a navigation has already left /website (the Outlet un-suppresses on
  // the way to /website/$channelId before the matched leaf settles). Only the
  // index path may redirect; otherwise this redirect hijacks the in-flight
  // navigation back to channels[0] (the browser-tabs blank-tab race).
  const onIndexPath = useRouterState({
    select: (s) => s.location.pathname === "/website",
  });

  if (isLoading) return null;

  if (!onIndexPath || activeTabIsBlank) return null;

  if (channels.length > 0) {
    // Empty tab strip → the new-tab screen, not a redirect that re-opens a tab.
    if (hasNoTabs) return <BlankTabView />;
    return (
      <Navigate
        to="/website/$channelId"
        params={{ channelId: channels[0].id }}
        replace
      />
    );
  }

  return (
    <Flex
      direction="column"
      align="center"
      justify="center"
      height="100%"
      gap="3"
      className="px-6 text-center"
    >
      <Flex direction="column" gap="1">
        <Text size="3" weight="bold" className="text-gray-12">
          No channels yet
        </Text>
        <Text size="2" className="text-gray-10">
          Create a channel to get its own canvases, tasks, and settings.
        </Text>
      </Flex>
      <Button variant="primary" onClick={() => setModalOpen(true)}>
        <PlusIcon size={14} />
        Create channel
      </Button>
      <CreateChannelModal open={modalOpen} onOpenChange={setModalOpen} />
    </Flex>
  );
}
