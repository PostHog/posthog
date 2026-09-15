import { ArrowSquareOutIcon, SparkleIcon } from "@phosphor-icons/react";
import {
  type ContextDocument,
  parseContextDocument,
  serializeContextDocument,
} from "@posthog/core/canvas/contextDocument";
import { Button, Text, ToggleGroup, ToggleGroupItem } from "@posthog/quill";
import { CreateChannelModal } from "@posthog/ui/features/canvas/components/CreateChannelModal";
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
import { ContextEmptyHero } from "./ContextEmptyHero";
import { GoalsScoreboard } from "./GoalsScoreboard";
import { KnowledgeBriefing } from "./KnowledgeBriefing";
import { RawContextEditor } from "./RawContextEditor";
import { ReferencesRail } from "./ReferencesRail";
import { SpaceSignals } from "./SpaceSignals";

type View = "overview" | "source";

interface SpaceContextPageProps {
  channelId: string;
  channelName: string;
  store: ContextDocumentStore;
  /** Shown when the document lives in the context wiki. */
  onOpenInWiki?: () => void;
}

/**
 * The Context tab of a space. One CONTEXT.md underneath, read as a briefing:
 * the goals on top, the knowledge as the body, references beside it, and
 * what agents found below.
 */
export function SpaceContextPage({
  channelId,
  channelName,
  store,
  onOpenInWiki,
}: SpaceContextPageProps) {
  const [view, setView] = useState<View>("overview");
  const [agentOpen, setAgentOpen] = useState(false);
  const [writing, setWriting] = useState(false);
  const doc = useMemo(
    () => parseContextDocument(store.content),
    [store.content],
  );
  const isBlank =
    !doc.knowledge.trim() &&
    doc.goals.length === 0 &&
    doc.links.length === 0 &&
    doc.objects.length === 0;
  const referenceCount = doc.links.length + doc.objects.length;

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
            {isBlank ? (
              "Every agent working in this space reads this first."
            ) : (
              <>
                {store.updatedAt ? (
                  <>
                    Updated <RelativeTimestamp timestamp={store.updatedAt} />
                    {" · "}
                  </>
                ) : null}
                {countLabel(doc.goals.length, "goal")}
                {" · "}
                {countLabel(referenceCount, "reference")}
              </>
            )}
          </PageHeaderDescription>
        </PageHeaderHeading>
        <PageHeaderActions>
          {onOpenInWiki ? (
            <Button variant="outline" size="sm" onClick={onOpenInWiki}>
              <ArrowSquareOutIcon size={14} />
              Open in wiki
            </Button>
          ) : null}
          {!isBlank ? (
            <Button
              variant="outline"
              size="sm"
              onClick={() => setAgentOpen(true)}
            >
              <SparkleIcon size={14} />
              Update with agent
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
          <div className="mx-auto flex w-full max-w-[960px] flex-col gap-8 px-6 pt-6 pb-16">
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
            ) : isBlank && !writing ? (
              <>
                <ContextEmptyHero
                  channelName={channelName}
                  onAskAgent={() => setAgentOpen(true)}
                  onWrite={() => setWriting(true)}
                />
                <SpaceSignals channelId={channelId} />
              </>
            ) : (
              <>
                <GoalsScoreboard
                  goals={doc.goals}
                  onChange={(goals) => saveDoc({ ...doc, goals })}
                  isSaving={store.isSaving}
                />
                <div className="grid @3xl:grid-cols-[minmax(0,1fr)_260px] gap-8">
                  <KnowledgeBriefing
                    knowledge={doc.knowledge}
                    onSave={(knowledge) => saveDoc({ ...doc, knowledge })}
                    onAskAgent={() => setAgentOpen(true)}
                    isSaving={store.isSaving}
                    startEditing={writing && isBlank}
                  />
                  <ReferencesRail
                    links={doc.links}
                    objects={doc.objects}
                    onLinksChange={(links) => saveDoc({ ...doc, links })}
                    onObjectsChange={(objects) => saveDoc({ ...doc, objects })}
                    isSaving={store.isSaving}
                  />
                </div>
                <SpaceSignals channelId={channelId} />
              </>
            )}
          </div>
        </div>
      )}

      <CreateChannelModal
        open={agentOpen}
        onOpenChange={setAgentOpen}
        existingContext={{ channelId, channelName }}
      />
    </div>
  );
}

function countLabel(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
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
