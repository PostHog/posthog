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
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import {
  type ContextDocumentStore,
  useLegacyContextDocumentStore,
  useWikiContextDocumentStore,
} from "@posthog/ui/features/canvas/hooks/useContextDocumentStore";
import { useChannelContextWikiPage } from "@posthog/ui/features/context-wiki/hooks/useContextWiki";
import { useContextLayerFlag } from "@posthog/ui/features/feature-flags/useContextLayerFlag";
import { LoadingState } from "@posthog/ui/primitives/LoadingState";
import type { ReactNode } from "react";

export interface ResolvedContextDocument {
  store: ContextDocumentStore;
  channelName: string;
  /** Set when the document lives in the context wiki. */
  wikiPath: string | null;
}

interface SpaceContextDocumentProps {
  channelId: string;
  children: (resolved: ResolvedContextDocument) => ReactNode;
}

/**
 * Resolves where a space's CONTEXT.md lives (a context wiki page, or the
 * legacy channel instructions) and hands whoever renders it one document
 * store either way. The Context tab and the CONTEXT.md page both sit on top
 * of this, so they cannot disagree about which document they show.
 */
export function SpaceContextDocument({
  channelId,
  children,
}: SpaceContextDocumentProps) {
  const contextLayerEnabled = useContextLayerFlag();
  const wikiPage = useChannelContextWikiPage(channelId, contextLayerEnabled);

  if (contextLayerEnabled && wikiPage.isLoading) {
    return <LoadingState />;
  }

  if (contextLayerEnabled && wikiPage.data) {
    return (
      <WikiDocument
        key={wikiPage.data.path}
        channelId={channelId}
        path={wikiPage.data.path}
      >
        {children}
      </WikiDocument>
    );
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

  return <LegacyDocument channelId={channelId}>{children}</LegacyDocument>;
}

function useChannelName(channelId: string): string {
  const spacesLayout = useChannelsLayout();
  const { channels } = useChannels();
  return (
    channels.find((c) => c.id === channelId)?.name ??
    (spacesLayout ? "this space" : "this channel")
  );
}

function WikiDocument({
  channelId,
  path,
  children,
}: SpaceContextDocumentProps & { path: string }) {
  const store = useWikiContextDocumentStore(path);
  const channelName = useChannelName(channelId);
  return <>{children({ store, channelName, wikiPath: path })}</>;
}

function LegacyDocument({ channelId, children }: SpaceContextDocumentProps) {
  const store = useLegacyContextDocumentStore(channelId);
  const channelName = useChannelName(channelId);
  return <>{children({ store, channelName, wikiPath: null })}</>;
}
