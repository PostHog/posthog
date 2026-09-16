import { ArrowSquareOutIcon, SparkleIcon } from "@phosphor-icons/react";
import {
  type ContextDocument,
  type ContextGoal,
  parseContextDocument,
  serializeContextDocument,
} from "@posthog/core/canvas/contextDocument";
import { Button, Text } from "@posthog/quill";
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
import { KnowledgeList } from "./KnowledgeList";
import { SignalsMargin } from "./SignalsMargin";

interface SpaceContextPageProps {
  channelId: string;
  channelName: string;
  store: ContextDocumentStore;
  /** Shown when the document lives in the context wiki. */
  onOpenInWiki?: () => void;
}

/**
 * The Context tab of a space in three zones. Goals: what the space is trying
 * to move. Business knowledge: everything a person told it, the briefing and
 * every doc and object as one list of rows. Signals: what agents and source
 * products found about those rows. Knowledge is written once and grows long;
 * signals change daily, so they sit beside it in a column that stays put
 * while the knowledge scrolls, and come first when the page is too narrow
 * for two columns. One CONTEXT.md underneath.
 */
export function SpaceContextPage({
  channelId,
  channelName,
  store,
  onOpenInWiki,
}: SpaceContextPageProps) {
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
          <div className="mx-auto flex w-full max-w-[1100px] flex-col gap-6 px-8 pt-8 pb-24">
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

            {isBlank && !writing ? (
              <ContextEmptyHero
                channelName={channelName}
                onAskAgent={() => setAgentOpen(true)}
                onWrite={() => setWriting(true)}
              />
            ) : (
              <div className="flex min-w-0 flex-col gap-10">
                <GoalsList
                  goals={doc.goals}
                  onChange={(goals) => saveDoc({ ...doc, goals })}
                  onAskAgentForMeasure={askAgentForMeasure}
                  isSaving={store.isSaving}
                />
                <div className="grid @4xl:grid-cols-[minmax(0,1fr)_300px] grid-cols-1 @4xl:gap-14 gap-10">
                  <div className="@4xl:order-none order-last min-w-0">
                    <KnowledgeList
                      knowledge={doc.knowledge}
                      links={doc.links}
                      objects={doc.objects}
                      onKnowledgeSave={(knowledge) =>
                        saveDoc({ ...doc, knowledge })
                      }
                      onLinksChange={(links) => saveDoc({ ...doc, links })}
                      onObjectsChange={(objects) =>
                        saveDoc({ ...doc, objects })
                      }
                      onAskAgent={() => setAgentOpen(true)}
                      isSaving={store.isSaving}
                      startWriting={writing && isBlank}
                    />
                  </div>
                  <div className="min-w-0">
                    <div className="@4xl:sticky @4xl:top-0">
                      <SignalsMargin objects={doc.objects} />
                    </div>
                  </div>
                </div>
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
