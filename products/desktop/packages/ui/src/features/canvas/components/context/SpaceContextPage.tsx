import { ArrowSquareOutIcon, SparkleIcon } from "@phosphor-icons/react";
import {
  type ContextDocument,
  type ContextGoal,
  parseContextDocument,
  serializeContextDocument,
} from "@posthog/core/canvas/contextDocument";
import { spaceFilesFolder } from "@posthog/core/canvas/contextFiles";
import { Button, cn, Text } from "@posthog/quill";
import { isTerminalStatus, type Task } from "@posthog/shared/domain-types";
import { CreateChannelModal } from "@posthog/ui/features/canvas/components/CreateChannelModal";
import {
  buildGoalMeasurePrompt,
  goalMeasureTaskTitle,
} from "@posthog/ui/features/canvas/contextPrompt";
import { GOAL_MEASURE_AGENT } from "@posthog/ui/features/canvas/goalMeasureAgent";
import {
  type GoalMeasureTask,
  readGoalMeasureTaskIds,
  writeGoalMeasureTaskIds,
} from "@posthog/ui/features/canvas/goalMeasureTasks";
import { useChannelFeed } from "@posthog/ui/features/canvas/hooks/useChannelFeed";
import type { ContextDocumentStore } from "@posthog/ui/features/canvas/hooks/useContextDocumentStore";
import { useGenerateContext } from "@posthog/ui/features/canvas/hooks/useGenerateContext";
import { useContextLayerFlag } from "@posthog/ui/features/feature-flags/useContextLayerFlag";
import { LoadingState } from "@posthog/ui/primitives/LoadingState";
import {
  PageHeader,
  PageHeaderActions,
  PageHeaderDescription,
  PageHeaderHeading,
  PageHeaderTitle,
  PageHeaderTitleRow,
} from "@posthog/ui/primitives/PageHeader";
import { RelativeTimestamp } from "@posthog/ui/primitives/RelativeTimestamp";
import { Spinner } from "@posthog/ui/primitives/Spinner";
import { navigateToChannelTask } from "@posthog/ui/router/navigationBridge";
import { useEffect, useMemo, useState } from "react";
import { ContextEmptyHero } from "./ContextEmptyHero";
import { GoalsList } from "./GoalsList";
import { KnowledgeList } from "./KnowledgeList";
import { MarkdownFileDialog } from "./MarkdownFileDialog";
import { SignalsMargin } from "./SignalsMargin";

const COLUMN = "mx-auto w-full max-w-[1100px] px-8";

interface SpaceContextPageProps {
  channelId: string;
  channelName: string;
  store: ContextDocumentStore;
  /** The document's path in the context wiki; null when it lives in folder instructions. */
  wikiPath: string | null;
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
  wikiPath,
  onOpenInWiki,
}: SpaceContextPageProps) {
  const [agentOpen, setAgentOpen] = useState(false);
  const [editingContextFile, setEditingContextFile] = useState(false);
  const [measureTaskIds, setMeasureTaskIds] = useState<Record<string, string>>(
    () => readGoalMeasureTaskIds(channelId),
  );
  useEffect(() => {
    setMeasureTaskIds(readGoalMeasureTaskIds(channelId));
  }, [channelId]);
  const { tasks: channelTasks, isLoading: channelTasksLoading } =
    useChannelFeed(channelId);
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
  const measureTasks = useMemo(() => {
    const map = new Map<string, GoalMeasureTask>();
    for (const goal of doc.goals) {
      const taskId = measureTaskIds[goal.name];
      if (taskId && goal.measure === null) {
        map.set(
          goal.name,
          taskStateFor(taskId, channelTasks, channelTasksLoading),
        );
      }
    }
    return map;
  }, [doc.goals, measureTaskIds, channelTasks, channelTasksLoading]);

  const rememberTask = (key: string, taskId: string) => {
    const next = { ...measureTaskIds, [key]: taskId };
    setMeasureTaskIds(next);
    writeGoalMeasureTaskIds(channelId, next);
  };

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
      agent: GOAL_MEASURE_AGENT,
    });
    if (task) rememberTask(goal.name, task.id);
  };

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <PageHeader className="px-0">
        <div className={COLUMN}>
          <PageHeaderHeading>
            <PageHeaderTitleRow>
              <PageHeaderTitle>Context</PageHeaderTitle>
              {store.isRefreshing || store.isSaving ? (
                <Spinner size="xs" aria-hidden="true" />
              ) : null}
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
            </PageHeaderTitleRow>
            <PageHeaderDescription>
              {isBlank ? (
                "Every agent working in this space reads this first."
              ) : store.updatedAt ? (
                <>
                  Updated <RelativeTimestamp timestamp={store.updatedAt} />
                </>
              ) : null}
            </PageHeaderDescription>
          </PageHeaderHeading>
        </div>
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
          <div className={cn(COLUMN, "flex flex-col gap-6 pt-10 pb-24")}>
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

            {isBlank ? (
              <ContextEmptyHero
                channelName={channelName}
                onAskAgent={() => setAgentOpen(true)}
                onWrite={() => setEditingContextFile(true)}
              />
            ) : (
              <div className="flex min-w-0 flex-col gap-10">
                <GoalsList
                  goals={doc.goals}
                  onChange={(goals) => saveDoc({ ...doc, goals })}
                  onAskAgentForMeasure={askAgentForMeasure}
                  measureTasks={measureTasks}
                  onOpenMeasureTask={(taskId) =>
                    navigateToChannelTask(channelId, taskId)
                  }
                  isSaving={store.isSaving}
                />
                <div className="grid @4xl:grid-cols-[minmax(0,1fr)_300px] grid-cols-1 @4xl:gap-14 gap-10">
                  <div className="@4xl:order-none order-last min-w-0">
                    <KnowledgeList
                      channelName={channelName}
                      knowledge={doc.knowledge}
                      links={doc.links}
                      objects={doc.objects}
                      filesFolder={wikiPath ? spaceFilesFolder(wikiPath) : null}
                      onOpenContextFile={() => setEditingContextFile(true)}
                      onLinksChange={(links) => saveDoc({ ...doc, links })}
                      onObjectsChange={(objects) =>
                        saveDoc({ ...doc, objects })
                      }
                      isSaving={store.isSaving}
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

      {editingContextFile ? (
        <MarkdownFileDialog
          fileName="CONTEXT.md"
          description={`Every agent working in ${channelName} reads this first.`}
          store={store}
          template={`# ${channelName}\n\n`}
          onClose={() => setEditingContextFile(false)}
        />
      ) : null}
    </div>
  );
}

function taskStateFor(
  taskId: string,
  channelTasks: Task[],
  loading: boolean,
): GoalMeasureTask {
  const task = channelTasks.find((t) => t.id === taskId);
  const ended = task
    ? isTerminalStatus(task.latest_run?.status)
    : !loading && channelTasks.length > 0;
  return { taskId, state: ended ? "ended" : "running" };
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
