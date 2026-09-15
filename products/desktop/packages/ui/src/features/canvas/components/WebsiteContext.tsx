import { FileTextIcon } from "@phosphor-icons/react";
import { ContextWikiUnavailableError } from "@posthog/api-client/posthog-client";
import {
  Button,
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@posthog/quill";
import { ChannelHeader } from "@posthog/ui/features/canvas/components/ChannelHeader";
import { SpaceContextPage } from "@posthog/ui/features/canvas/components/context/SpaceContextPage";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import {
  useLegacyContextDocumentStore,
  useWikiContextDocumentStore,
} from "@posthog/ui/features/canvas/hooks/useContextDocumentStore";
import { useChannelContextWikiPage } from "@posthog/ui/features/context-wiki/hooks/useContextWiki";
import { useContextLayerFlag } from "@posthog/ui/features/feature-flags/useContextLayerFlag";
import { useSetHeaderContent } from "@posthog/ui/hooks/useSetHeaderContent";
import { LoadingState } from "@posthog/ui/primitives/LoadingState";
import { navigateToSpacesContext } from "@posthog/ui/router/navigationBridge";
import { useMemo } from "react";

interface WebsiteContextProps {
  channelId: string;
}

/**
 * The Context tab of a space. Resolves where the space's CONTEXT.md lives
 * (context wiki page, or legacy channel instructions) and hands the page one
 * document store either way.
 */
export function WebsiteContext({ channelId }: WebsiteContextProps) {
  const contextLayerEnabled = useContextLayerFlag();
  const wikiPage = useChannelContextWikiPage(channelId, contextLayerEnabled);
  const headerContent = useMemo(
    () => <ChannelHeader channelId={channelId} page="context" />,
    [channelId],
  );
  useSetHeaderContent(headerContent);

  if (contextLayerEnabled && wikiPage.isLoading) {
    return <LoadingState />;
  }

  if (contextLayerEnabled && wikiPage.data) {
    return <WikiContext channelId={channelId} path={wikiPage.data.path} />;
  }

  if (contextLayerEnabled && wikiPage.error) {
    const unavailable = wikiPage.error instanceof ContextWikiUnavailableError;
    return (
      <Empty>
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <FileTextIcon size={28} />
          </EmptyMedia>
          <EmptyTitle>
            {unavailable
              ? "Context wiki unavailable"
              : "Could not load context"}
          </EmptyTitle>
          <EmptyDescription>{wikiPage.error.message}</EmptyDescription>
        </EmptyHeader>
        {!unavailable ? (
          <EmptyContent>
            <Button variant="outline" onClick={() => wikiPage.refetch()}>
              Try again
            </Button>
          </EmptyContent>
        ) : null}
      </Empty>
    );
  }

  return <LegacyContext channelId={channelId} />;
}

function useChannelName(channelId: string): string {
  const spacesLayout = useChannelsLayout();
  const { channels } = useChannels();
  return (
    channels.find((c) => c.id === channelId)?.name ??
    (spacesLayout ? "this space" : "this channel")
  );
}

function WikiContext({ channelId, path }: { channelId: string; path: string }) {
  const store = useWikiContextDocumentStore(path);
  const channelName = useChannelName(channelId);
  return (
    <SpaceContextPage
      key={path}
      channelId={channelId}
      channelName={channelName}
      store={store}
      onOpenInWiki={() => navigateToSpacesContext(path)}
    />
  );
}

function LegacyContext({ channelId }: WebsiteContextProps) {
  const store = useLegacyContextDocumentStore(channelId);
  const channelName = useChannelName(channelId);
  return (
    <SpaceContextPage
      channelId={channelId}
      channelName={channelName}
      store={store}
    />
  );
}
