import { ArrowSquareOutIcon, SparkleIcon } from "@phosphor-icons/react";
import {
  type ContextDocument,
  type ContextGoal,
  parseContextDocument,
  serializeContextDocument,
} from "@posthog/core/canvas/contextDocument";
import { Button, Text, ToggleGroup, ToggleGroupItem } from "@posthog/quill";
import type { Task } from "@posthog/shared/domain-types";
import { CreateChannelModal } from "@posthog/ui/features/canvas/components/CreateChannelModal";
import { channelPageIcon } from "@posthog/ui/features/canvas/components/channelPages";
import {
  buildGoalMeasurePrompt,
  goalMeasureTaskTitle,
} from "@posthog/ui/features/canvas/contextPrompt";
import type { ContextDocumentStore } from "@posthog/ui/features/canvas/hooks/useContextDocumentStore";
import { useGenerateContext } from "@posthog/ui/features/canvas/hooks/useGenerateContext";
import { useContextLayerFlag } from "@posthog/ui/features/feature-flags/useContextLayerFlag";
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
import { navigateToChannelTask } from "@posthog/ui/router/navigationBridge";
import { useMemo, useState } from "react";
import { ContextEmptyHero } from "./ContextEmptyHero";
import { GoalsList } from "./GoalsList";
import { KnowledgeBriefing } from "./KnowledgeBriefing";
import { RawContextEditor } from "./RawContextEditor";
import { ReferencesRail } from "./ReferencesRail";
import { SignalsMargin } from "./SignalsMargin";

type View = "overview" | "source";

interface SpaceContextPageProps {
  channelId: string;
  channelName: string;
  store: ContextDocumentStore;
  /** Shown when the document lives in the context wiki. */
  onOpenInWiki?: () => void;
}

/**
 * The Context tab of a space: a document with a live margin. The document is
 * what people author, goals first and the briefing under them. The margin is
 * what is observed: the objects the space owns with their live state, and the
 * signals about them. One CONTEXT.md underneath.
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
  const [measureTask, setMeasureTask] = useState<{
    goal: string;
    task: Task;
  } | null>(null);
  const contextLayerEnabled = useContextLayerFlag();
  const { generate } = useGenerateContext();
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

  const askAgentForMeasure = async (goal: ContextGoal) => {
    const task = await generate({
      channelId,
      channelName,
      description: "",
      prompt: buildGoalMeasurePrompt({
        channelName,
        channelId,
        goalName: goal.name,
        goalWhy: goal.why,
        contextLayerEnabled,
      }),
      title: goalMeasureTaskTitle(goal.name),
    });
    if (task) setMeasureTask({ goal: goal.name, task });
  };

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
          <div className="mx-auto flex w-full max-w-[1040px] flex-col gap-6 px-8 pt-8 pb-20">
            {store.saveError ? (
              <Notice
                tone="warning"
                message={
                  store.isConflict
                    ? "Someone else saved a newer version while you were editing. Reload to see it, then make your change again."
                    : `Could not save: ${store.saveError.message}`
                }
                action={
                  <Button variant="outline" size="sm" onClick={store.refetch}>
                    Reload
                  </Button>
                }
              />
            ) : null}

            {measureTask ? (
              <Notice
                message={`An agent is writing the measure for "${measureTask.goal}". The number appears here when it publishes.`}
                action={
                  <>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() =>
                        navigateToChannelTask(channelId, measureTask.task.id)
                      }
                    >
                      Open task
                    </Button>
                    <Button
                      variant="default"
                      size="sm"
                      onClick={() => setMeasureTask(null)}
                    >
                      Dismiss
                    </Button>
                  </>
                }
              />
            ) : null}

            {view === "source" ? (
              <RawContextEditor
                content={store.content}
                onSave={store.save}
                isSaving={store.isSaving}
              />
            ) : isBlank && !writing ? (
              <ContextEmptyHero
                channelName={channelName}
                onAskAgent={() => setAgentOpen(true)}
                onWrite={() => setWriting(true)}
              />
            ) : (
              <div className="grid @3xl:grid-cols-[minmax(0,1fr)_288px] gap-x-16 gap-y-10">
                <div className="flex min-w-0 flex-col gap-10">
                  <GoalsList
                    goals={doc.goals}
                    onChange={(goals) => saveDoc({ ...doc, goals })}
                    onAskAgentForMeasure={askAgentForMeasure}
                    isSaving={store.isSaving}
                  />
                  <KnowledgeBriefing
                    knowledge={doc.knowledge}
                    onSave={(knowledge) => saveDoc({ ...doc, knowledge })}
                    onAskAgent={() => setAgentOpen(true)}
                    isSaving={store.isSaving}
                    startEditing={writing && isBlank}
                  />
                </div>
                <aside className="@3xl:sticky @3xl:top-0 flex min-w-0 flex-col gap-8 @3xl:self-start">
                  <ReferencesRail
                    links={doc.links}
                    objects={doc.objects}
                    onLinksChange={(links) => saveDoc({ ...doc, links })}
                    onObjectsChange={(objects) => saveDoc({ ...doc, objects })}
                    isSaving={store.isSaving}
                  />
                  <SignalsMargin objects={doc.objects} />
                </aside>
              </div>
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

function Notice({
  message,
  action,
  tone = "default",
}: {
  message: string;
  action: React.ReactNode;
  tone?: "default" | "warning";
}) {
  return (
    <div className="flex items-center justify-between gap-3 border-border border-y py-2.5">
      <Text
        size="xs"
        className={tone === "warning" ? "text-warning-foreground" : undefined}
      >
        {message}
      </Text>
      <div className="flex shrink-0 items-center gap-1">{action}</div>
    </div>
  );
}
