import { ArrowSquareOutIcon, SparkleIcon } from "@phosphor-icons/react";
import {
  type BrokenBlock,
  type ContextDocument,
  type ContextGoal,
  parseContextDocument,
  serializeContextDocument,
} from "@posthog/core/canvas/contextDocument";
import { spaceFilesFolder } from "@posthog/core/canvas/contextFiles";
import { Button, cn, Text } from "@posthog/quill";
import { CreateChannelModal } from "@posthog/ui/features/canvas/components/CreateChannelModal";
import {
  buildGoalMeasurePrompt,
  GOAL_MEASURE_AGENT,
  goalMeasureTaskTitle,
} from "@posthog/ui/features/canvas/contextPrompt";
import { goalMeasureTasks } from "@posthog/ui/features/canvas/goalMeasureTasks";
import { useChannelFeed } from "@posthog/ui/features/canvas/hooks/useChannelFeed";
import type { ContextDocumentStore } from "@posthog/ui/features/canvas/hooks/useContextDocumentStore";
import { useGenerateContext } from "@posthog/ui/features/canvas/hooks/useGenerateContext";
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
import { useEffect, useMemo, useRef, useState } from "react";
import { ContextEmptyHero } from "./ContextEmptyHero";
import { GoalsList } from "./GoalsList";
import { KnowledgeList } from "./KnowledgeList";
import { MarkdownFileDialog } from "./MarkdownFileDialog";

const COLUMN = "mx-auto w-full max-w-[1100px] px-8";
// Under the tab strip the content spans the pane at the tabs' own inset, so a
// section's action lands at the same right edge as the page's own.
const TAB_COLUMN = "w-full px-6";

interface SpaceContextPageProps {
  channelId: string;
  channelName: string;
  store: ContextDocumentStore;
  wikiPath: string | null;
  /** The page sits under a tab strip that already says "Context". */
  hideTitle?: boolean;
  onOpenInWiki?: () => void;
}

export function SpaceContextPage({
  channelId,
  channelName,
  store,
  wikiPath,
  hideTitle = false,
  onOpenInWiki,
}: SpaceContextPageProps) {
  const [agentOpen, setAgentOpen] = useState(false);
  const [editingContextFile, setEditingContextFile] = useState(false);
  const { tasks: channelTasks } = useChannelFeed(channelId);
  const { generate } = useGenerateContext();
  const doc = useMemo(
    () => parseContextDocument(store.content),
    [store.content],
  );
  const ready = !store.isLoading && store.error === null;
  const brokenIn = (...keys: BrokenBlock["key"][]) =>
    doc.broken.find((block) => keys.includes(block.key))?.error;
  const isBlank =
    !doc.knowledge.trim() &&
    doc.goals.length === 0 &&
    doc.links.length === 0 &&
    doc.objects.length === 0;
  const measureTasks = useMemo(
    () => goalMeasureTasks(doc.goals, channelTasks),
    [doc.goals, channelTasks],
  );
  const latest = useRef({ doc, store });
  useEffect(() => {
    latest.current = { doc, store };
  });
  const agentRunning = [...measureTasks.values()].some(
    (task) => task.state === "running",
  );
  useEffect(() => {
    if (!agentRunning) return;
    const timer = setInterval(store.refetch, 30_000);
    return () => clearInterval(timer);
  }, [agentRunning, store.refetch]);

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
        goal,
        contextLayerEnabled: wikiPath !== null,
      }),
      title: goalMeasureTaskTitle(goal.name),
      agent: GOAL_MEASURE_AGENT,
    });
    if (!task) return;
    const current = latest.current;
    await current.store.save(
      serializeContextDocument({
        ...current.doc,
        goals: current.doc.goals.map((entry) =>
          entry.id === goal.id ? { ...entry, task: task.id } : entry,
        ),
      }),
    );
  };

  // Everything under the page's chrome, shared by both header shapes.
  const body = (
    <>
      {store.isLoading ? <LoadingState className="flex-1" /> : null}

      {store.error ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-2 px-6">
          <Text size="xs" variant="muted">
            Could not load this space's context: {store.error.message}
          </Text>
          <Button variant="outline" size="sm" onClick={store.refetch}>
            Try again
          </Button>
        </div>
      ) : null}
      {ready ? (
        <div className="min-h-0 flex-1 overflow-y-auto">
          <div
            className={cn(
              hideTitle ? TAB_COLUMN : COLUMN,
              "flex flex-col gap-6",
              hideTitle ? "pt-6 pb-24" : "pt-10 pb-24",
            )}
          >
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
                  error={brokenIn("goals")}
                />
                <KnowledgeList
                  channelName={channelName}
                  links={doc.links}
                  objects={doc.objects}
                  filesFolder={wikiPath ? spaceFilesFolder(wikiPath) : null}
                  onOpenContextFile={() => setEditingContextFile(true)}
                  onLinksChange={(links) => saveDoc({ ...doc, links })}
                  onObjectsChange={(objects) => saveDoc({ ...doc, objects })}
                  isSaving={store.isSaving}
                  error={brokenIn("reading", "watching")}
                />
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
    </>
  );

  const purpose = isBlank ? (
    "Every agent working in this space reads this first."
  ) : store.updatedAt ? (
    <>
      Updated <RelativeTimestamp timestamp={store.updatedAt} />
    </>
  ) : null;
  const actions = (
    <>
      {onOpenInWiki ? (
        <Button variant="outline" size="sm" onClick={onOpenInWiki}>
          <ArrowSquareOutIcon size={14} />
          Open in wiki
        </Button>
      ) : null}
      {!isBlank ? (
        <Button variant="outline" size="sm" onClick={() => setAgentOpen(true)}>
          <SparkleIcon size={14} />
          Update with agent
        </Button>
      ) : null}
    </>
  );

  // Under a tab strip that already says "Context" there is no title to stack
  // under, so the page's one line of chrome carries the purpose on the left and
  // the actions on the right rather than a header block with an empty row in it.
  if (hideTitle) {
    return (
      <div className="flex h-full flex-col overflow-hidden">
        <div className="shrink-0 border-border border-b">
          <div className="flex h-11 w-full items-center gap-2 px-6">
            <Text size="xs" variant="muted" className="min-w-0 truncate">
              {purpose}
            </Text>
            {store.isRefreshing || store.isSaving ? (
              <Spinner size="xs" aria-hidden="true" />
            ) : null}
            <div className="ml-auto flex shrink-0 items-center gap-2">
              {actions}
            </div>
          </div>
        </div>
        {body}
      </div>
    );
  }

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
              <PageHeaderActions>{actions}</PageHeaderActions>
            </PageHeaderTitleRow>
            <PageHeaderDescription>{purpose}</PageHeaderDescription>
          </PageHeaderHeading>
        </div>
      </PageHeader>
      {body}
    </div>
  );
}
