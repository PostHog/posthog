import { ArrowSquareOutIcon } from "@phosphor-icons/react";
import {
  type ContextDocument,
  parseContextDocument,
  serializeContextDocument,
} from "@posthog/core/canvas/contextDocument";
import { Button, Text, ToggleGroup, ToggleGroupItem } from "@posthog/quill";
import { channelPageIcon } from "@posthog/ui/features/canvas/components/channelPages";
import type { ContextDocumentStore } from "@posthog/ui/features/canvas/hooks/useContextDocumentStore";
import { LoadingState } from "@posthog/ui/primitives/LoadingState";
import {
  PageHeader,
  PageHeaderActions,
  PageHeaderChip,
  PageHeaderDescription,
  PageHeaderHeading,
  PageHeaderTitle,
  PageHeaderTitleRow,
} from "@posthog/ui/primitives/PageHeader";
import { RelativeTimestamp } from "@posthog/ui/primitives/RelativeTimestamp";
import { Spinner } from "@posthog/ui/primitives/Spinner";
import { useMemo, useState } from "react";
import { GoalsSection } from "./GoalsSection";
import { KnowledgeSection } from "./KnowledgeSection";
import { LinksSection } from "./LinksSection";
import { ObjectsSection } from "./ObjectsSection";
import { RawContextEditor } from "./RawContextEditor";
import { SpaceAgentsSection } from "./SpaceAgentsSection";

type View = "overview" | "source";

interface SpaceContextPageProps {
  channelId: string;
  channelName: string;
  store: ContextDocumentStore;
  /** Shown when the document lives in the context wiki. */
  onOpenInWiki?: () => void;
}

/**
 * The Context tab of a space. One CONTEXT.md underneath, edited as knowledge,
 * files and links, PostHog objects, and goals, with the source one toggle away.
 */
export function SpaceContextPage({
  channelId,
  channelName,
  store,
  onOpenInWiki,
}: SpaceContextPageProps) {
  const [view, setView] = useState<View>("overview");
  const doc = useMemo(
    () => parseContextDocument(store.content),
    [store.content],
  );

  const saveDoc = (next: ContextDocument) =>
    store.save(serializeContextDocument(next));

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <PageHeader>
        <PageHeaderHeading>
          <PageHeaderTitleRow>
            <PageHeaderTitle>Context</PageHeaderTitle>
            {store.versionLabel ? (
              <PageHeaderChip icon={channelPageIcon("context", { size: 12 })}>
                {store.versionLabel}
              </PageHeaderChip>
            ) : null}
            {store.isRefreshing || store.isSaving ? (
              <Spinner size="xs" aria-hidden="true" />
            ) : null}
          </PageHeaderTitleRow>
          <PageHeaderDescription>
            What every agent working in this space reads before it starts: what
            it is, where the detail lives, which PostHog objects it owns, and
            the goals it moves.
          </PageHeaderDescription>
        </PageHeaderHeading>
        <PageHeaderActions>
          {onOpenInWiki ? (
            <Button variant="outline" size="sm" onClick={onOpenInWiki}>
              <ArrowSquareOutIcon size={14} />
              Open in context wiki
            </Button>
          ) : null}
          <ToggleGroup
            value={[view]}
            onValueChange={(next: string[]) => {
              const selected = next[0];
              if (selected === "overview" || selected === "source") {
                setView(selected);
              }
            }}
            aria-label="Context view"
            className="gap-1"
          >
            <ToggleGroupItem value="overview" size="sm" variant="outline">
              Overview
            </ToggleGroupItem>
            <ToggleGroupItem value="source" size="sm" variant="outline">
              CONTEXT.md
            </ToggleGroupItem>
          </ToggleGroup>
        </PageHeaderActions>
      </PageHeader>

      {store.isLoading ? (
        <LoadingState className="flex-1" />
      ) : store.error ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-2 px-6">
          <Text size="xs" variant="muted">
            Could not load this space's context: {store.error.message}
          </Text>
          <Button variant="outline" size="sm" onClick={store.refetch}>
            Try again
          </Button>
        </div>
      ) : (
        <div className="@container min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto flex w-full max-w-[920px] flex-col gap-8 px-6 pt-6 pb-16">
            {store.saveError ? (
              <SaveErrorBanner
                message={
                  store.isConflict
                    ? "Someone else saved a newer version while you were editing. Reload to see it, then make your change again."
                    : `Could not save: ${store.saveError.message}`
                }
                onReload={store.refetch}
              />
            ) : null}

            {view === "source" ? (
              <RawContextEditor
                content={store.content}
                onSave={store.save}
                isSaving={store.isSaving}
              />
            ) : (
              <>
                <KnowledgeSection
                  channelId={channelId}
                  channelName={channelName}
                  knowledge={doc.knowledge}
                  onSave={(knowledge) => saveDoc({ ...doc, knowledge })}
                  isSaving={store.isSaving}
                />
                <LinksSection
                  links={doc.links}
                  onChange={(links) => saveDoc({ ...doc, links })}
                  isSaving={store.isSaving}
                />
                <ObjectsSection
                  objects={doc.objects}
                  onChange={(objects) => saveDoc({ ...doc, objects })}
                  isSaving={store.isSaving}
                />
                <GoalsSection
                  goals={doc.goals}
                  onChange={(goals) => saveDoc({ ...doc, goals })}
                  isSaving={store.isSaving}
                />
                <SpaceAgentsSection
                  channelId={channelId}
                  channelName={channelName}
                  doc={doc}
                />
              </>
            )}

            {store.updatedAt ? (
              <Text size="xxs" variant="muted" className="text-center">
                Last saved <RelativeTimestamp timestamp={store.updatedAt} />
              </Text>
            ) : null}
          </div>
        </div>
      )}
    </div>
  );
}

function SaveErrorBanner({
  message,
  onReload,
}: {
  message: string;
  onReload: () => void;
}) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-lg border border-warning bg-card px-4 py-2.5">
      <Text size="xs" className="text-warning-foreground">
        {message}
      </Text>
      <Button variant="outline" size="sm" onClick={onReload}>
        Reload
      </Button>
    </div>
  );
}
