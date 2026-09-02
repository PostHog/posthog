import {
  ArrowSquareOutIcon,
  CaretLeftIcon,
  PaperPlaneRightIcon,
  XIcon,
} from "@phosphor-icons/react";
import type { DocSchemas } from "@posthog/api-client/docs";
import { latestAgentMessageText } from "@posthog/core/sessions/latestTurnMessage";
import {
  Button,
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  InputGroupAddon,
  InputGroupButton,
  Separator,
  Spinner,
  Text,
  ThreadItemGroup,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import type { Task } from "@posthog/shared/domain-types";
import { MentionComposer } from "@posthog/ui/features/canvas/components/MentionComposer";
import { useOrgMembers } from "@posthog/ui/features/canvas/hooks/useOrgMembers";
import { usePinnedAutoScroll } from "@posthog/ui/features/canvas/hooks/usePinnedAutoScroll";
import { useSessionConnection } from "@posthog/ui/features/sessions/hooks/useSessionConnection";
import { useSessionViewState } from "@posthog/ui/features/sessions/hooks/useSessionViewState";
import { usePendingPermissionsForTask } from "@posthog/ui/features/sessions/sessionStore";
import { DocMark } from "@posthog/ui/primitives/DocMark";
import { toast } from "@posthog/ui/primitives/toast";
import { Link } from "@tanstack/react-router";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useDiscussionMutations } from "../hooks/useDocDiscussions";
import {
  agentStateOf,
  type TaskState,
  threadPosts,
  useDocThread,
} from "../hooks/useDocThread";
import { DocPostRow, DocStreamingRow } from "./DocPostRow";
import { DocThreadRow, threadStanding } from "./DocThreadRow";
import { WatchHeaderActions, WatchStrip } from "./DocWatchCard";
import { DocWatchDossier } from "./DocWatchDossier";

export type ThreadsPanelView =
  | { view: "list" }
  | { view: "thread"; anchorKey: string };

export interface PendingThread {
  anchorKey: string;
  anchorText: string;
}

/** The task behind a thread, off the space's task list. */
export function taskFor(
  thread: DocSchemas.DiscussionThread,
  tasks: Task[],
): Task | undefined {
  return thread.task_id
    ? tasks.find((task) => task.id === thread.task_id)
    : undefined;
}

/**
 * The threads beside a doc: a list, and one thread open at a time, the way a
 * Slack thread opens. People and the agent post in the same column.
 */
export function DocThreadsPanel({
  view,
  onView,
  onClose,
  threads,
  isLoading,
  pending,
  onCancelPending,
  docId,
  channelId,
  docTitle,
  tasks,
  currentUserEmail,
  onJumpToAnchor,
  onAddToPage,
  onAgentStarted,
}: {
  view: ThreadsPanelView;
  onView: (view: ThreadsPanelView) => void;
  onClose: () => void;
  threads: DocSchemas.DiscussionThread[];
  isLoading: boolean;
  pending: PendingThread | null;
  onCancelPending: () => void;
  docId: string;
  channelId: string;
  docTitle: string;
  tasks: Task[];
  currentUserEmail?: string | null;
  onJumpToAnchor: (anchorKey: string) => void;
  onAddToPage: (text: string) => void;
  onAgentStarted: () => void;
}) {
  const [showHandled, setShowHandled] = useState(false);

  const open =
    view.view === "thread"
      ? (threads.find((thread) => thread.anchor_key === view.anchorKey) ?? null)
      : null;
  const openPending =
    view.view === "thread" && !open && pending?.anchorKey === view.anchorKey
      ? pending
      : null;

  return (
    <aside className="@2xl:static absolute inset-y-0 right-0 @2xl:z-auto z-10 flex @2xl:w-96 w-full @2xl:shrink-0 flex-col border-(--gray-5) border-l bg-(--gray-1)">
      {view.view === "thread" && (open || openPending) ? (
        <ThreadView
          key={view.anchorKey}
          thread={open}
          pending={openPending}
          docId={docId}
          channelId={channelId}
          docTitle={docTitle}
          task={open ? taskFor(open, tasks) : undefined}
          currentUserEmail={currentUserEmail}
          onBack={() => {
            if (openPending) onCancelPending();
            onView({ view: "list" });
          }}
          onClose={onClose}
          onJumpToAnchor={onJumpToAnchor}
          onAddToPage={onAddToPage}
          onAgentStarted={onAgentStarted}
        />
      ) : (
        <ThreadList
          threads={threads}
          isLoading={isLoading}
          tasks={tasks}
          showHandled={showHandled}
          onShowHandled={setShowHandled}
          onOpen={(anchorKey) => onView({ view: "thread", anchorKey })}
          onClose={onClose}
        />
      )}
    </aside>
  );
}

function PanelHeader({
  children,
  onClose,
}: {
  children: React.ReactNode;
  onClose: () => void;
}) {
  return (
    <>
      <div className="flex h-10 shrink-0 items-center gap-1 px-2">
        {children}
        <Button
          size="icon"
          variant="default"
          aria-label="Close threads"
          onClick={onClose}
        >
          <XIcon size={15} />
        </Button>
      </div>
      <Separator />
    </>
  );
}

function ThreadList({
  threads,
  isLoading,
  tasks,
  showHandled,
  onShowHandled,
  onOpen,
  onClose,
}: {
  threads: DocSchemas.DiscussionThread[];
  isLoading: boolean;
  tasks: Task[];
  showHandled: boolean;
  onShowHandled: (show: boolean) => void;
  onOpen: (anchorKey: string) => void;
  onClose: () => void;
}) {
  const openThreads = threads.filter((thread) => !thread.resolved);
  const handledCount = threads.length - openThreads.length;
  const shown = showHandled ? threads : openThreads;
  // Newest activity first, the way a list of conversations reads.
  const ordered = [...shown].sort(
    (left, right) => Date.parse(lastAt(right)) - Date.parse(lastAt(left)),
  );

  return (
    <>
      <PanelHeader onClose={onClose}>
        <Text weight="medium" className="min-w-0 flex-1 truncate px-1">
          Threads
          {openThreads.length > 0 ? (
            <span className="ml-1.5 text-(--gray-9)">{openThreads.length}</span>
          ) : null}
        </Text>
        {handledCount > 0 ? (
          <button
            type="button"
            className="cursor-pointer px-1 text-(--gray-10) text-xs hover:text-(--gray-12)"
            onClick={() => onShowHandled(!showHandled)}
          >
            {showHandled ? "Hide handled" : `Show handled (${handledCount})`}
          </button>
        ) : null}
      </PanelHeader>

      <div className="min-h-0 flex-1 overflow-y-auto p-1.5">
        {isLoading ? (
          <div className="flex justify-center py-8">
            <Spinner />
          </div>
        ) : ordered.length === 0 ? (
          <Empty className="h-full border-0">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <DocMark variant="discussion" state="open" size={16} />
              </EmptyMedia>
              <EmptyTitle>No threads yet</EmptyTitle>
              <EmptyDescription>
                Select words and press Discuss to start one. Tag @agent in a
                thread to bring the agent in, or type + in the page for a data
                point.
              </EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : (
          <div className="flex flex-col gap-0.5">
            {ordered.map((thread) => (
              <DocThreadRow
                key={thread.id}
                thread={thread}
                standing={threadStanding(
                  thread,
                  agentStateOf(thread, taskFor(thread, tasks)),
                )}
                selected={false}
                onOpen={() => onOpen(thread.anchor_key)}
              />
            ))}
          </div>
        )}
      </div>
    </>
  );
}

function lastAt(thread: DocSchemas.DiscussionThread): string {
  const last = thread.replies[thread.replies.length - 1];
  return last?.created_at ?? thread.created_at;
}

function ThreadView({
  thread,
  pending,
  docId,
  channelId,
  docTitle,
  task: listedTask,
  currentUserEmail,
  onBack,
  onClose,
  onJumpToAnchor,
  onAddToPage,
  onAgentStarted,
}: {
  thread: DocSchemas.DiscussionThread | null;
  pending: PendingThread | null;
  docId: string;
  channelId: string;
  docTitle: string;
  task: Task | undefined;
  currentUserEmail?: string | null;
  onBack: () => void;
  onClose: () => void;
  onJumpToAnchor: (anchorKey: string) => void;
  onAddToPage: (text: string) => void;
  onAgentStarted: () => void;
}) {
  const { members } = useOrgMembers();
  const [draft, setDraft] = useState("");
  const handle = useDocThread({
    docId,
    channelId,
    docTitle,
    thread,
    pending,
    onAgentStarted,
  });
  const task = handle.task ?? listedTask;
  const taskState = agentStateOf(thread, task);
  const posts = useMemo(() => (thread ? threadPosts(thread) : []), [thread]);
  const watchMutation = useDiscussionMutations(docId).watch;
  const [pendingAction, setPendingAction] =
    useState<DocSchemas.WatchActionKind | null>(null);
  const [dossierOpen, setDossierOpen] = useState(false);
  const threadId = thread?.id;
  const onWatchAction = useCallback(
    (body: DocSchemas.WatchActionBody) => {
      if (!threadId) return;
      setPendingAction(body.action);
      watchMutation.mutate(
        { threadId, body },
        {
          onError: (error) =>
            toast.error("The watch did not take that", {
              description:
                error instanceof Error ? error.message : String(error),
            }),
          onSettled: () => setPendingAction(null),
        },
      );
    },
    [threadId, watchMutation],
  );
  const { containerRef, contentRef, onScroll } = usePinnedAutoScroll();

  const anchorKey = thread?.anchor_key ?? pending?.anchorKey ?? "";
  const anchorText = thread?.anchor_text ?? pending?.anchorText ?? "";
  const kind = thread?.kind ?? "text";
  const standing = thread
    ? threadStanding(thread, taskState)
    : { variant: "discussion" as const, state: "open" as const };

  const submit = () => {
    const content = draft.trim();
    if (!content || handle.isSending) return;
    setDraft("");
    handle.send(content).catch(() => setDraft(content));
  };

  const needsAnswer =
    thread?.kind === "data" &&
    !thread.answer &&
    (taskState === "done" || taskState === "failed");

  return (
    <>
      <PanelHeader onClose={onClose}>
        <Button
          size="icon"
          variant="default"
          aria-label="Back to threads"
          onClick={onBack}
        >
          <CaretLeftIcon size={15} />
        </Button>
        <DocMark variant={standing.variant} state={standing.state} size={14} />
        <Text weight="medium" className="min-w-0 flex-1 truncate px-1">
          Thread
        </Text>
        {thread?.watch ? (
          <WatchHeaderActions
            watch={thread.watch}
            onAction={onWatchAction}
            pendingAction={pendingAction}
          />
        ) : thread ? (
          <Button
            size="sm"
            variant="default"
            onClick={() => handle.setResolved(!thread.resolved)}
          >
            {thread.resolved ? "Reopen" : "Mark handled"}
          </Button>
        ) : null}
        {thread?.task_id ? (
          <Tooltip>
            <TooltipTrigger
              render={
                <Button
                  size="icon"
                  variant="default"
                  aria-label="Open the task"
                  render={
                    <Link
                      to="/spaces/$channelId/tasks/$taskId"
                      params={{ channelId, taskId: thread.task_id }}
                    />
                  }
                />
              }
            >
              <ArrowSquareOutIcon size={15} />
            </TooltipTrigger>
            <TooltipContent>Open the task</TooltipContent>
          </Tooltip>
        ) : null}
      </PanelHeader>

      <button
        type="button"
        className="doc-thread-quote mx-3 mt-3 cursor-pointer text-left hover:text-(--gray-12)"
        data-kind={kind}
        title="Show this in the page"
        onClick={() => onJumpToAnchor(anchorKey)}
      >
        {kind === "data"
          ? `+ ${anchorText}`
          : anchorText || "a place in the doc"}
      </button>
      {thread?.watch ? (
        <>
          <WatchStrip
            watch={thread.watch}
            onHistory={() => setDossierOpen(true)}
          />
          <DocWatchDossier
            thread={thread}
            open={dossierOpen}
            onOpenChange={setDossierOpen}
            onAction={onWatchAction}
            pendingAction={pendingAction}
          />
        </>
      ) : null}

      <div
        ref={containerRef}
        className="min-h-0 flex-1 overflow-y-auto"
        onScroll={onScroll}
      >
        <div ref={contentRef} className="py-2">
          {posts.length === 0 && !thread ? (
            <Text size="sm" className="px-3 py-6 text-center text-(--gray-10)">
              Say something about it. Tag @agent to bring the agent in.
            </Text>
          ) : null}
          <ThreadItemGroup>
            {posts.map((post) => (
              <DocPostRow
                key={post.id}
                post={post}
                currentUserEmail={currentUserEmail}
                onAddToPage={onAddToPage}
              />
            ))}
          </ThreadItemGroup>
          {task ? (
            <LiveTurn task={task} posts={posts} taskState={taskState} />
          ) : null}
          {needsAnswer ? (
            <div className="mx-3 my-2 flex items-center justify-between gap-2 rounded-(--radius-3) border border-(--gray-5) px-3 py-2">
              <Text size="sm" className="text-(--gray-11)">
                The agent did not hand in a query.
              </Text>
              <Button
                size="sm"
                variant="default"
                disabled={handle.isSending}
                onClick={() => {
                  void handle.send(`@agent ${anchorText}`);
                }}
              >
                Ask again
              </Button>
            </div>
          ) : null}
        </div>
      </div>

      <div className="border-(--gray-5) border-t p-2">
        <MentionComposer
          value={draft}
          onValueChange={setDraft}
          onSubmit={submit}
          members={members}
          allowAgentMention
          autoFocus
          placeholder="Reply… @agent brings the agent in"
          rows={2}
          inputClassName="max-h-40 text-[13px]"
        >
          <InputGroupAddon align="block-end" className="p-1">
            <span className="ml-auto flex items-center gap-1">
              <InputGroupButton
                variant="primary"
                size="icon-sm"
                aria-label="Send"
                disabled={!draft.trim() || handle.isSending}
                onClick={submit}
              >
                <PaperPlaneRightIcon size={14} />
              </InputGroupButton>
            </span>
          </InputGroupAddon>
        </MentionComposer>
      </div>
    </>
  );
}

/**
 * The turn the agent is on, while it is on it. This window attaches to the run
 * so the text streams; other windows see the post when it lands.
 */
function LiveTurn({
  task,
  posts,
  taskState,
}: {
  task: Task;
  posts: DocSchemas.DiscussionPost[];
  taskState: TaskState | null;
}) {
  const { session, repoPath, isCloud, events } = useSessionViewState(
    task.id,
    task,
  );
  useSessionConnection({ taskId: task.id, task, session, repoPath, isCloud });
  const pendingPermissions = usePendingPermissionsForTask(task.id);
  const [seenAt, setSeenAt] = useState(0);
  const liveText = useMemo(() => latestAgentMessageText(events), [events]);

  // The persisted post replaces the streamed text; the two must not both show.
  const lastAgentPost = [...posts]
    .reverse()
    .find((post) => post.author_kind === "agent");
  useEffect(() => {
    if (lastAgentPost) setSeenAt(Date.parse(lastAgentPost.created_at));
  }, [lastAgentPost]);
  const streaming =
    taskState === "working" &&
    liveText &&
    (!lastAgentPost ||
      (Date.now() - seenAt > 1_000 &&
        !lastAgentPost.content.includes(liveText.slice(0, 40))));

  if (pendingPermissions.size > 0) {
    return (
      <div className="flex items-center gap-2 px-3 py-2 text-(--amber-11) text-[12px]">
        <DocMark variant="agent" state="waiting" size={12} />
        The agent is waiting for you in the task.
      </div>
    );
  }
  if (taskState === "failed") {
    return (
      <div className="flex items-center gap-2 px-3 py-2 text-(--red-11) text-[12px]">
        <DocMark variant="agent" state="failed" size={12} />
        The agent's run failed.
      </div>
    );
  }
  if (taskState !== "working") return null;
  return <DocStreamingRow text={streaming ? liveText : null} />;
}
