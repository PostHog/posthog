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
  GOAL_MEASURE_AGENT,
  goalMeasureTaskTitle,
} from "@posthog/ui/features/canvas/contextPrompt";
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

const EMPTY_DOCUMENT: ContextDocument = {
  frontmatter: "",
  knowledge: "",
  links: [],
  objects: [],
  goals: [],
};

interface SpaceContextPageProps {
  channelId: string;
  channelName: string;
  store: ContextDocumentStore;
  wikiPath: string | null;
  onOpenInWiki?: () => void;
}

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
  const parsed = useMemo(() => parseDocument(store.content), [store.content]);
  const doc = parsed.doc;
  const problem = store.isLoading ? null : documentProblem(store, parsed.error);
  const ready = !store.isLoading && problem === null;
  const isBlank =
    !doc.knowledge.trim() &&
    doc.goals.length === 0 &&
    doc.links.length === 0 &&
    doc.objects.length === 0;
  const measureTasks = useMemo(
    () =>
      new Map(
        doc.goals.flatMap((goal) => {
          const taskId = measureTaskIds[goal.name];
          if (!taskId || goal.measure !== null) return [];
          const task = taskStateFor(taskId, channelTasks, channelTasksLoading);
          return [[goal.name, task] as const];
        }),
      ),
    [doc.goals, measureTaskIds, channelTasks, channelTasksLoading],
  );

  const rememberTask = (key: string, taskId: string) => {
    const next = { ...measureTaskIds, [key]: taskId };
    setMeasureTaskIds(next);
    writeGoalMeasureTaskIds(channelId, next);
  };

  const saveDoc = (next: ContextDocument) =>
    store.save(serializeContextDocument(next));
  const knowledgeStore: ContextDocumentStore = {
    ...store,
    content: doc.knowledge,
    save: (knowledge) => saveDoc({ ...doc, knowledge }),
  };

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
              {isBlank
                ? "Every agent working in this space reads this first."
                : null}
              {!isBlank && store.updatedAt ? (
                <>
                  Updated <RelativeTimestamp timestamp={store.updatedAt} />
                </>
              ) : null}
            </PageHeaderDescription>
          </PageHeaderHeading>
        </div>
      </PageHeader>

      {store.isLoading ? <LoadingState className="flex-1" /> : null}
      {problem ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-2 px-6">
          <Text size="xs" variant="muted" className="whitespace-pre-wrap">
            {problem.text}
          </Text>
          <Button variant="outline" size="sm" onClick={store.refetch}>
            {problem.action}
          </Button>
        </div>
      ) : null}
      {ready ? (
        <div className="@container min-h-0 flex-1 overflow-y-auto">
          <div className={cn(COLUMN, "flex flex-col gap-6 pt-10 pb-24")}>
            {store.saveError ? (
              <div className="flex items-center justify-between gap-3 border-border border-y py-2.5">
                <Text size="xs" className="text-warning-foreground">
                  {store.isConflict
                    ? "Someone else saved a newer version while you were editing. Reload to see it, then make your change again."
                    : `Could not save: ${store.saveError.message}`}
                </Text>
                <Button
                  variant="outline"
                  size="sm"
                  className="shrink-0"
                  onClick={store.refetch}
                >
                  Reload
                </Button>
              </div>
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
      ) : null}

      <CreateChannelModal
        open={agentOpen}
        onOpenChange={setAgentOpen}
        existingContext={{ channelId, channelName }}
      />

      {editingContextFile ? (
        <MarkdownFileDialog
          fileName="CONTEXT.md"
          description={`Every agent working in ${channelName} reads this first. Goals, links and files are managed on the Context page and stay out of this text.`}
          store={knowledgeStore}
          template={`# ${channelName}\n\n`}
          onClose={() => setEditingContextFile(false)}
        />
      ) : null}
    </div>
  );
}

function parseDocument(content: string): {
  doc: ContextDocument;
  error: string | null;
} {
  try {
    return { doc: parseContextDocument(content), error: null };
  } catch (cause) {
    return {
      doc: EMPTY_DOCUMENT,
      error: cause instanceof Error ? cause.message : String(cause),
    };
  }
}

function documentProblem(
  store: ContextDocumentStore,
  parseError: string | null,
): { text: string; action: string } | null {
  if (store.error) {
    return {
      text: `Could not load this space's context: ${store.error.message}`,
      action: "Try again",
    };
  }
  if (parseError) {
    return {
      text: `The goals, reading and watching lists in this document could not be read. Fix the frontmatter in the wiki, then reload.\n\n${parseError}`,
      action: "Reload",
    };
  }
  return null;
}

function taskStateFor(
  taskId: string,
  channelTasks: Task[],
  loading: boolean,
): GoalMeasureTask {
  const task = channelTasks.find((candidate) => candidate.id === taskId);
  const ended = task
    ? isTerminalStatus(task.latest_run?.status)
    : !loading && channelTasks.length > 0;
  return { taskId, state: ended ? "ended" : "running" };
}
