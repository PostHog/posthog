import { ChannelHeader } from "@posthog/ui/features/canvas/components/ChannelHeader";
import { SpaceContextPage } from "@posthog/ui/features/canvas/components/context/SpaceContextPage";
import { SpaceContextDocument } from "@posthog/ui/features/canvas/components/SpaceContextDocument";
import { useSetHeaderContent } from "@posthog/ui/hooks/useSetHeaderContent";
import { navigateToSpacesContext } from "@posthog/ui/router/navigationBridge";
import { useMemo } from "react";

interface WebsiteContextProps {
  channelId: string;
}

/** The Context tab of a space. */
export function WebsiteContext({ channelId }: WebsiteContextProps) {
  const headerContent = useMemo(
    () => <ChannelHeader channelId={channelId} page="context" />,
    [channelId],
  );
  useSetHeaderContent(headerContent);

  return (
    <SpaceContextDocument channelId={channelId}>
      {({ store, channelName, wikiPath }) => (
        <SpaceContextPage
          channelId={channelId}
          channelName={channelName}
          store={store}
          wikiPath={wikiPath}
          onOpenInWiki={
            wikiPath ? () => navigateToSpacesContext(wikiPath) : undefined
          }
        />
      )}
    </SpaceContextDocument>
  );
}
