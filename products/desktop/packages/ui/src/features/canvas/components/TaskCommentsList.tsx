import {
  CaretDownIcon,
  ChatCircleIcon,
  FunnelSimpleIcon,
  GitPullRequestIcon,
} from "@phosphor-icons/react";
import type { ResourceComment } from "@posthog/api-client/posthog-client";
import type { ThreadTimelineRow } from "@posthog/core/canvas/threadTimeline";
import { commentTargetKey } from "@posthog/core/comments/anchors";
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Spinner,
} from "@posthog/quill";
import type {
  Task,
  TaskThreadMessage,
  UserBasic,
} from "@posthog/shared/domain-types";
import { iconForTemplate } from "@posthog/ui/features/canvas/components/canvasTemplateIcon";
import {
  buildRows,
  type CommentSource,
  commentSources,
  openCanvasFromUrl,
  taskCommentTarget,
} from "@posthog/ui/features/canvas/components/taskArtifactRows";
import {
  byNewestActivity,
  prCommentThreads,
  resourceCommentThreads,
  type SourceKind,
  type TaskCommentThread,
  threadSourceOptions,
} from "@posthog/ui/features/canvas/components/taskCommentThreads";
import { useOrgMembers } from "@posthog/ui/features/canvas/hooks/useOrgMembers";
import { useTaskRuns } from "@posthog/ui/features/canvas/hooks/useTaskRuns";
import { usePrCommentActions } from "@posthog/ui/features/code-review/hooks/usePrCommentActions";
import { openPrInReview } from "@posthog/ui/features/code-review/openPrInReview";
import { useReviewNavigationStore } from "@posthog/ui/features/code-review/reviewNavigationStore";
import { usePrTitles } from "@posthog/ui/features/git-interaction/usePrDetails";
import {
  useActiveArtifactId,
  usePanelLayoutStore,
} from "@posthog/ui/features/panels/panelLayoutStore";
import { usePrCommentsForUrls } from "@posthog/ui/features/pr-review/usePrCommentsForUrls";
import { usePrReviewThreadsForUrls } from "@posthog/ui/features/pr-review/usePrReviewThreadsForUrls";
import { useCommentNavigationStore } from "@posthog/ui/features/sessions/commentNavigationStore";
import { CommentComposer } from "@posthog/ui/features/sessions/components/CommentComposer";
import { CommentThreadCard } from "@posthog/ui/features/sessions/components/CommentThreadCard";
import type { HighlightResolution } from "@posthog/ui/features/sessions/components/commentViewTypes";
import { readCommentContext } from "@posthog/ui/features/sessions/components/commentViewTypes";
import {
  useCommentsForTargetsQuery,
  useCreateComment,
  useSetCommentResolved,
} from "@posthog/ui/features/sessions/components/useComments";
import { FileIcon } from "@posthog/ui/primitives/FileIcon";
import { useEffect, useMemo, useRef, useState } from "react";

const EMPTY_COMMENTS: ResourceComment[] = [];
/** The whole task's threads in one request; slower than a single artifact's own
 *  poll because this one fans out across every resource. */
const POLL_INTERVAL_MS = 15_000;
const PULSE_MS = 1_200;
const ALL_SOURCES = "all";

type StateFilter = "open" | "resolved";

/** The icon a source shows wherever it's named — the card label and the
 *  filter menu — so the two always agree. */
function sourceIcon(kind: SourceKind, label: string, size = 12) {
  switch (kind) {
    case "pr":
      return (
        <GitPullRequestIcon size={size} className="shrink-0 text-gray-11" />
      );
    case "canvas":
      return iconForTemplate("", { size, className: "text-violet-9" });
    case "task":
      return <ChatCircleIcon size={size} className="shrink-0 text-gray-11" />;
    default:
      return <FileIcon filename={label} size={size} />;
  }
}

function SourceLabel({ thread }: { thread: TaskCommentThread }) {
  const replies = thread.entries.length - 1;
  return (
    <span className="mb-1 flex min-w-0 items-center gap-1.5 text-muted-foreground text-xs">
      {sourceIcon(thread.sourceKind, thread.sourceLabel)}
      <span className="min-w-0 truncate" title={thread.sourceLabel}>
        {thread.sourceLabel}
      </span>
      {thread.origin.kind === "pr-review" && (
        <span className="min-w-0 truncate">
          · {thread.origin.filePath.split("/").at(-1)}
        </span>
      )}
      {replies > 0 && (
        <span className="shrink-0">
          · {replies} {replies === 1 ? "reply" : "replies"}
        </span>
      )}
    </span>
  );
}

/**
 * A PostHog comment thread. Its own component so it can hold the mutations for
 * its thread's resource — the list spans several, each with its own target.
 */
function ResourceThreadRow({
  thread,
  source,
  root,
  taskId,
  members,
  selected,
  pulsing,
  resolution,
  onOpen,
}: {
  thread: TaskCommentThread;
  source: CommentSource;
  root: ResourceComment;
  taskId: string;
  members: UserBasic[];
  selected: boolean;
  pulsing: boolean;
  resolution?: HighlightResolution;
  onOpen: () => void;
}) {
  const createComment = useCreateComment(source.target, taskId);
  const setResolved = useSetCommentResolved(source.target);

  return (
    <CommentThreadCard
      threadId={thread.id}
      entries={thread.entries}
      selected={selected}
      pulsing={pulsing}
      resolved={thread.resolved}
      members={members}
      resolution={resolution}
      busy={createComment.isPending || setResolved.isPending}
      source={<SourceLabel thread={thread} />}
      onSelect={onOpen}
      onReply={(content, mentions) =>
        createComment.mutate({
          content,
          sourceCommentId: root.id,
          context: readCommentContext(root) ?? { anchor: { kind: "document" } },
          mentions,
        })
      }
      onResolve={(resolved) => setResolved.mutate({ root, resolved })}
    />
  );
}

/** A GitHub thread. Reply and resolve go to GitHub, not to PostHog. */
function PrThreadRow({
  thread,
  selected,
  pulsing,
  onOpen,
}: {
  thread: TaskCommentThread;
  selected: boolean;
  pulsing: boolean;
  onOpen: () => void;
}) {
  const origin = thread.origin;
  const prUrl = origin.kind === "resource" ? null : origin.prUrl;
  const { reply, resolve } = usePrCommentActions(prUrl);
  const [busy, setBusy] = useState(false);

  const run = async (action: () => Promise<boolean>) => {
    setBusy(true);
    await action();
    setBusy(false);
  };

  return (
    <CommentThreadCard
      threadId={thread.id}
      entries={thread.entries}
      selected={selected}
      pulsing={pulsing}
      resolved={thread.resolved}
      // GitHub bodies mention GitHub logins, so the org member picker would
      // insert markup nobody on that side understands.
      members={[]}
      busy={busy}
      source={<SourceLabel thread={thread} />}
      // Only inline review threads accept replies and resolution; conversation
      // comments are read here and linked out to GitHub to act on.
      canReply={origin.kind === "pr-review"}
      canResolve={origin.kind === "pr-review"}
      viewHref={origin.kind === "pr-conversation" ? origin.url : undefined}
      onSelect={onOpen}
      onReply={(content) =>
        run(() =>
          origin.kind === "pr-review"
            ? reply(origin.rootCommentId, content)
            : Promise.resolve(false),
        )
      }
      onResolve={(resolved) =>
        run(() =>
          origin.kind === "pr-review"
            ? resolve(origin.threadNodeId, resolved)
            : Promise.resolve(false),
        )
      }
    />
  );
}

/**
 * Every comment thread on the task: its artifacts, its canvases, its pull
 * requests, and the task itself. Selecting one opens where it lives and locates
 * it there, which is why no surface carries a thread list of its own.
 */
export function TaskCommentsList({
  task,
  timeline,
}: {
  task: Task;
  timeline: ThreadTimelineRow<TaskThreadMessage>[];
}) {
  const { runs } = useTaskRuns(task.id);
  const { members } = useOrgMembers();
  const openArtifactTab = usePanelLayoutStore((state) => state.openArtifactTab);
  const activeArtifactId = useActiveArtifactId(task.id);
  const requestCommentFocus = useCommentNavigationStore(
    (state) => state.requestCommentFocus,
  );
  const focus = useCommentNavigationStore(
    (state) => state.focusByTask[task.id],
  );
  const resolutionsByTarget = useCommentNavigationStore(
    (state) => state.resolutionsByTarget,
  );
  const [stateFilter, setStateFilter] = useState<StateFilter>("open");
  const [sourceFilter, setSourceFilter] = useState<string>(ALL_SOURCES);
  const [pulseThreadId, setPulseThreadId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");

  const rows = useMemo(
    () => buildRows(task, timeline, runs),
    [task, timeline, runs],
  );
  const sources = useMemo(() => commentSources(task.id, rows), [task.id, rows]);
  const targets = useMemo(
    () => sources.map((source) => source.target),
    [sources],
  );
  const commentsQuery = useCommentsForTargetsQuery(targets, {
    live: true,
    intervalMs: POLL_INTERVAL_MS,
  });
  const prUrls = useMemo(
    () => rows.flatMap((row) => (row.kind === "pr" ? [row.url] : [])),
    [rows],
  );
  const prConversation = usePrCommentsForUrls(prUrls);
  const prReviews = usePrReviewThreadsForUrls(prUrls);
  const prTitles = usePrTitles(prUrls);

  const taskTarget = useMemo(() => taskCommentTarget(task.id), [task.id]);
  const taskSourceKey = commentTargetKey(taskTarget);
  const createTaskComment = useCreateComment(taskTarget, task.id);

  const threads = useMemo(() => {
    const reviewByUrl = new Map(prReviews.byUrl);
    const conversationByUrl = new Map(prConversation.byUrl);
    const resourceThreads = resourceCommentThreads(
      commentsQuery.data ?? EMPTY_COMMENTS,
      sources,
    );
    const prThreads = prUrls.flatMap((prUrl) =>
      prCommentThreads(
        prUrl,
        prTitles[prUrl] ?? `PR #${prUrl.split("/").at(-1)}`,
        reviewByUrl.get(prUrl) ?? [],
        conversationByUrl.get(prUrl) ?? [],
      ),
    );
    return [...resourceThreads, ...prThreads].sort(byNewestActivity);
  }, [
    commentsQuery.data,
    sources,
    prUrls,
    prTitles,
    prReviews.byUrl,
    prConversation.byUrl,
  ]);

  const sourceOptions = useMemo(() => threadSourceOptions(threads), [threads]);
  const sourceLabel =
    sourceFilter === ALL_SOURCES
      ? "All sources"
      : (sourceOptions.find((option) => option.key === sourceFilter)?.label ??
        "All sources");
  // Every source that could ever hold a thread, whether or not it has one yet.
  // Validating against this rather than the loaded threads lets the filter
  // follow an artifact whose comments haven't arrived, and lets the task and
  // PR sources stay selectable while empty.
  const knownSourceKeys = useMemo(() => {
    const keys = new Set(
      sources.map((source) => commentTargetKey(source.target)),
    );
    for (const prUrl of prUrls) keys.add(prUrl);
    return keys;
  }, [sources, prUrls]);

  // A source that can't exist any more (its artifact left the task) can't stay
  // selected, or the pane reads as empty with no hint why. Adjust during render
  // rather than in an effect, so the stale filter never commits first.
  if (sourceFilter !== ALL_SOURCES && !knownSourceKeys.has(sourceFilter)) {
    setSourceFilter(ALL_SOURCES);
  }

  // Follow the artifact on screen until the reader picks a source themselves;
  // after that the filter is theirs, not the pane's.
  const sourceFilterTouched = useRef(false);
  useEffect(() => {
    if (sourceFilterTouched.current) return;
    setSourceFilter(
      activeArtifactId
        ? commentTargetKey({ scope: "task_artifact", itemId: activeArtifactId })
        : ALL_SOURCES,
    );
  }, [activeArtifactId]);

  const inSource = (thread: TaskCommentThread) =>
    sourceFilter === ALL_SOURCES || thread.sourceKey === sourceFilter;
  const scoped = threads.filter(inSource);
  const openCount = scoped.filter((thread) => !thread.resolved).length;
  const resolvedCount = scoped.length - openCount;
  const visibleThreads = scoped.filter(
    (thread) => thread.resolved === (stateFilter === "resolved"),
  );

  // A thread picked on the artifact itself has to surface here, even when a
  // filter is hiding it. Each request is honoured once, by nonce: resolving the
  // focused thread later must not drag the filters along with it.
  const focusedThreadId = focus?.threadId ?? null;
  const handledNonceRef = useRef<number | null>(null);
  useEffect(() => {
    if (!focus || handledNonceRef.current === focus.nonce) return;
    const focused = threads.find((thread) => thread.id === focus.threadId);
    // The thread may still be loading, so wait rather than guess its filters.
    if (!focused) return;
    handledNonceRef.current = focus.nonce;
    setStateFilter(focused.resolved ? "resolved" : "open");
    setSourceFilter((current) =>
      current === ALL_SOURCES || current === focused.sourceKey
        ? current
        : ALL_SOURCES,
    );
    setPulseThreadId(focus.threadId);
    requestAnimationFrame(() => {
      document
        .querySelector(
          `[data-comment-thread-id="${CSS.escape(focus.threadId)}"]`,
        )
        ?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    });
  }, [focus, threads]);
  // The pulse fades on its own; owning the timer in its own effect keeps it
  // cleaned up on the next pulse or on unmount, without a stray ref.
  useEffect(() => {
    if (!pulseThreadId) return;
    const timer = setTimeout(() => setPulseThreadId(null), PULSE_MS);
    return () => clearTimeout(timer);
  }, [pulseThreadId]);

  const openThread = (thread: TaskCommentThread) => {
    const origin = thread.origin;
    if (origin.kind === "pr-review" || origin.kind === "pr-conversation") {
      openPrInReview(task.id, origin.prUrl);
      if (origin.kind === "pr-review") {
        // The review pane scrolls by file; a specific comment is as close as it
        // gets until it grows a per-thread target.
        useReviewNavigationStore
          .getState()
          .requestScrollToFile(task.id, origin.filePath);
      }
      return;
    }
    const { source, root } = origin;
    if (source.kind === "canvas") {
      // Canvas comment surfaces land with the canvas work; until then this
      // opens the canvas itself rather than a dead deep link.
      openCanvasFromUrl(source.url)?.();
      return;
    }
    // A thread on the task itself has nowhere else to open — it lives here.
    if (source.kind === "task" || !source.runId) return;
    openArtifactTab(task.id, {
      runId: source.runId,
      artifactId: source.target.itemId,
      name: source.name,
    });
    requestCommentFocus(task.id, source.target, root.id);
  };

  const loading =
    commentsQuery.isLoading || prConversation.isLoading || prReviews.isLoading;

  return (
    // The parent scrolls the middle; the filters and the composer are pinned so
    // they stay reachable however long the thread list grows.
    <div className="flex min-h-full flex-col">
      <header className="sticky top-0 z-10 flex shrink-0 items-center justify-end gap-1 bg-gray-1 px-2 py-2">
        <DropdownMenu>
          <DropdownMenuTrigger
            render={
              <Button
                size="sm"
                aria-label="Filter by source"
                title={sourceLabel}
              >
                <span className="max-w-40 truncate">{sourceLabel}</span>
                <CaretDownIcon />
              </Button>
            }
          />
          {/* Wide, single-line rows: the label truncates at the end (with the
              full name on hover) and the count is pinned right with the shared
              ml-auto idiom, so a long PR title stays legible and aligned. */}
          <DropdownMenuContent align="end" sideOffset={6} className="w-80">
            <DropdownMenuRadioGroup
              value={sourceFilter}
              onValueChange={(value) => {
                sourceFilterTouched.current = true;
                setSourceFilter(value);
              }}
            >
              <DropdownMenuRadioItem value={ALL_SOURCES} className="gap-2">
                <FunnelSimpleIcon size={12} className="shrink-0 text-gray-11" />
                <span className="min-w-0 truncate">All sources</span>
                <span className="ml-auto shrink-0 pl-3 text-muted-foreground tabular-nums">
                  {threads.length}
                </span>
              </DropdownMenuRadioItem>
              {sourceOptions.map((option) => (
                <DropdownMenuRadioItem
                  key={option.key}
                  value={option.key}
                  title={option.label}
                  className="gap-2"
                >
                  {sourceIcon(option.kind, option.label)}
                  <span className="min-w-0 truncate">{option.label}</span>
                  <span className="ml-auto shrink-0 pl-3 text-muted-foreground tabular-nums">
                    {
                      threads.filter(
                        (thread) => thread.sourceKey === option.key,
                      ).length
                    }
                  </span>
                </DropdownMenuRadioItem>
              ))}
            </DropdownMenuRadioGroup>
          </DropdownMenuContent>
        </DropdownMenu>
        <DropdownMenu>
          <DropdownMenuTrigger
            render={
              <Button size="sm" aria-label="Filter comments">
                {stateFilter === "open" ? "Open" : "Resolved"}
                <CaretDownIcon />
              </Button>
            }
          />
          <DropdownMenuContent align="end" sideOffset={6}>
            <DropdownMenuRadioGroup
              value={stateFilter}
              onValueChange={(value) => setStateFilter(value as StateFilter)}
            >
              <DropdownMenuRadioItem value="open">
                Open ({openCount})
              </DropdownMenuRadioItem>
              <DropdownMenuRadioItem value="resolved">
                Resolved ({resolvedCount})
              </DropdownMenuRadioItem>
            </DropdownMenuRadioGroup>
          </DropdownMenuContent>
        </DropdownMenu>
      </header>
      <div className="flex-1 space-y-2 px-2 pt-3 pb-2">
        {loading && threads.length === 0 ? (
          <div className="flex justify-center py-8">
            <Spinner />
          </div>
        ) : visibleThreads.length === 0 ? (
          <Empty className="py-8">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <ChatCircleIcon />
              </EmptyMedia>
              <EmptyTitle>
                No {stateFilter === "open" ? "open" : "resolved"} comments
              </EmptyTitle>
              <EmptyDescription>
                {stateFilter === "open"
                  ? "Comment on the task below, or open an artifact and select text to start a thread there."
                  : "Resolved threads will appear here."}
              </EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : (
          visibleThreads.map((thread) =>
            thread.origin.kind === "resource" ? (
              <ResourceThreadRow
                key={thread.id}
                thread={thread}
                source={thread.origin.source}
                root={thread.origin.root}
                taskId={task.id}
                members={members}
                selected={thread.id === focusedThreadId}
                pulsing={thread.id === pulseThreadId}
                resolution={resolutionsByTarget[thread.sourceKey]?.get(
                  thread.id,
                )}
                onOpen={() => openThread(thread)}
              />
            ) : (
              <PrThreadRow
                key={thread.id}
                thread={thread}
                selected={thread.id === focusedThreadId}
                pulsing={thread.id === pulseThreadId}
                onOpen={() => openThread(thread)}
              />
            ),
          )
        )}
      </div>
      <footer className="sticky bottom-0 shrink-0 border-border border-t bg-background p-2">
        <CommentComposer
          value={draft}
          onValueChange={setDraft}
          onSubmit={(content, mentions) => {
            createTaskComment.mutate({
              content,
              context: { anchor: { kind: "document" } },
              mentions,
            });
            setDraft("");
            // Show the thread that was just opened: open state, and a source
            // filter that isn't hiding the task's own comments.
            setStateFilter("open");
            if (
              sourceFilter !== ALL_SOURCES &&
              sourceFilter !== taskSourceKey
            ) {
              setSourceFilter(ALL_SOURCES);
            }
          }}
          members={members}
          placeholder="Comment on this task… Type @ to mention someone"
          rows={2}
          disabled={createTaskComment.isPending}
        />
      </footer>
    </div>
  );
}
