import { FileMdIcon } from "@phosphor-icons/react";
import {
  parseContextDocument,
  serializeContextDocument,
} from "@posthog/core/canvas/contextDocument";
import { Button, Text } from "@posthog/quill";
import { ChannelHeader } from "@posthog/ui/features/canvas/components/ChannelHeader";
import { CreateChannelModal } from "@posthog/ui/features/canvas/components/CreateChannelModal";
import { SpaceContextDocument } from "@posthog/ui/features/canvas/components/SpaceContextDocument";
import type { ContextDocumentStore } from "@posthog/ui/features/canvas/hooks/useContextDocumentStore";
import { useSetHeaderContent } from "@posthog/ui/hooks/useSetHeaderContent";
import { LoadingState } from "@posthog/ui/primitives/LoadingState";
import { navigateToSpacesContext } from "@posthog/ui/router/navigationBridge";
import { useMemo, useState } from "react";
import { BriefingEditor } from "./BriefingEditor";
import { BriefingReader } from "./BriefingReader";
import { BRIEFING_TEMPLATE } from "./briefingSections";

interface ContextDocumentPageProps {
  channelId: string;
  editing: boolean;
  onEditingChange: (editing: boolean) => void;
}

/**
 * The CONTEXT.md page of a space: the briefing on its own, read or written,
 * with the Context tab one breadcrumb step back. Reading and writing are two
 * screens rather than one that changes shape, so a person always knows which
 * one they are on.
 */
export function ContextDocumentPage({
  channelId,
  editing,
  onEditingChange,
}: ContextDocumentPageProps) {
  const headerContent = useMemo(
    () => (
      <ChannelHeader
        channelId={channelId}
        page="context"
        leaf={{ icon: <FileMdIcon size={12} />, label: "CONTEXT.md" }}
      />
    ),
    [channelId],
  );
  useSetHeaderContent(headerContent);

  return (
    <SpaceContextDocument channelId={channelId}>
      {({ store, channelName, wikiPath }) => (
        <ResolvedDocument
          channelId={channelId}
          channelName={channelName}
          store={store}
          editing={editing}
          onEditingChange={onEditingChange}
          onOpenInWiki={
            wikiPath ? () => navigateToSpacesContext(wikiPath) : undefined
          }
        />
      )}
    </SpaceContextDocument>
  );
}

function ResolvedDocument({
  channelId,
  channelName,
  store,
  editing,
  onEditingChange,
  onOpenInWiki,
}: ContextDocumentPageProps & {
  channelName: string;
  store: ContextDocumentStore;
  onOpenInWiki?: () => void;
}) {
  const [agentOpen, setAgentOpen] = useState(false);
  // A seed is what the editor opens with when it is not the saved text: the
  // template for a blank document, or the text with a section appended.
  const [seed, setSeed] = useState<string | null>(null);
  const doc = useMemo(
    () => parseContextDocument(store.content),
    [store.content],
  );

  const startEditing = (nextSeed?: string) => {
    setSeed(nextSeed ?? null);
    onEditingChange(true);
  };

  const stopEditing = () => {
    setSeed(null);
    onEditingChange(false);
  };

  if (store.isLoading) {
    return <LoadingState className="h-full" />;
  }

  if (store.error) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 px-6">
        <Text size="xs" variant="muted">
          Could not load CONTEXT.md: {store.error.message}
        </Text>
        <Button variant="outline" size="sm" onClick={store.refetch}>
          Try again
        </Button>
      </div>
    );
  }

  return (
    <>
      {editing ? (
        <BriefingEditor
          channelName={channelName}
          knowledge={doc.knowledge}
          initialDraft={seed ?? (doc.knowledge.trim() || BRIEFING_TEMPLATE)}
          store={store}
          onSave={(knowledge) =>
            store.save(serializeContextDocument({ ...doc, knowledge }))
          }
          onDone={stopEditing}
        />
      ) : (
        <BriefingReader
          channelName={channelName}
          knowledge={doc.knowledge}
          store={store}
          onEdit={startEditing}
          onAskAgent={() => setAgentOpen(true)}
          onOpenInWiki={onOpenInWiki}
        />
      )}
      <CreateChannelModal
        open={agentOpen}
        onOpenChange={setAgentOpen}
        existingContext={{ channelId, channelName }}
      />
    </>
  );
}
