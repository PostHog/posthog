import { ChatCircleIcon } from "@phosphor-icons/react";
import type { ResourceComment } from "@posthog/api-client/posthog-client";
import type { ThreadTimelineRow } from "@posthog/core/canvas/threadTimeline";
import { commentTargetKey } from "@posthog/core/comments/anchors";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@posthog/quill";
import type {
  Task,
  TaskThreadMessage,
  UserBasic,
} from "@posthog/shared/domain-types";
import {
  ALL_SOURCES,
  CommentListHeader,
  type CommentStateFilter,
} from "@posthog/ui/features/canvas/components/CommentListHeader";
import { CommentThreadGroups } from "@posthog/ui/features/canvas/components/CommentThreadGroups";
import {
  buildRows,
  type CommentSource,
  commentSources,
  taskCommentTarget,
} from "@posthog/ui/features/canvas/components/taskArtifactRows";
import {
  byNewestThread,
  prCommentThreads,
  resourceCommentThreads,
  type TaskCommentThread,
  threadSourceOptions,
} from "@posthog/ui/features/canvas/components/taskCommentThreads";
import { useOrgMembers } from "@posthog/ui/features/canvas/hooks/useOrgMembers";
import { useTaskRuns } from "@posthog/ui/features/canvas/hooks/useTaskRuns";
import { canvasArtifactOpenHandler } from "@posthog/ui/features/canvas/utils/canvasArtifactNavigation";
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
import {
  type CommentResource,
  commentAgentContext,
} from "@posthog/ui/features/sessions/commentAgentContext";
import { useCommentNavigationStore } from "@posthog/ui/features/sessions/commentNavigationStore";
import { CommentComposer } from "@posthog/ui/features/sessions/components/CommentComposer";
import { CommentThreadCard } from "@posthog/ui/features/sessions/components/CommentThreadCard";
import type { HighlightResolution } from "@posthog/ui/features/sessions/components/commentViewTypes";
import { readCommentContext } from "@posthog/ui/features/sessions/components/commentViewTypes";
import {
  isOptimisticComment,
  useCommentsForTargetsQuery,
  useCommentsQuery,
  useCreateComment,
  useSetCommentResolved,
} from "@posthog/ui/features/sessions/components/useComments";
import { sendCommentToAgent } from "@posthog/ui/features/sessions/sendCommentToAgent";
import { LoadingState } from "@posthog/ui/primitives/LoadingState";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

const EMPTY_COMMENTS: ResourceComment[] = [];
/** The whole task's threads in one request; slower than a single artifact's own
 *  poll because this one fans out across every resource. */
const POLL_INTERVAL_MS = 30_000;
const PULSE_MS = 1_200;
// Keep task comments live, but bound the artifact and canvas poll so generated
// output cannot turn one Comments tab into an unbounded backend request.
const MAX_RESOURCE_COMMENT_TARGETS = 20;
// Each PR starts three GitHub-backed queries. Keep this cap at the source so a
// task with generated output cannot fan out into an unbounded number of requests.
const MAX_PR_COMMENT_SOURCES = 20;
const MAX_CONCURRENT_PR_SOURCES = 4;

function scrollThreadInPane(pane: HTMLElement, thread: HTMLElement): void {
  const paneRect = pane.getBoundingClientRect();
  const threadRect = thread.getBoundingClientRect();
  const offset =
    threadRect.top < paneRect.top
      ? threadRect.top - paneRect.top
      : threadRect.bottom > paneRect.bottom
        ? threadRect.bottom - paneRect.bottom
        : 0;
  if (offset !== 0) {
    pane.scrollTo({ top: pane.scrollTop + offset, behavior: "smooth" });
  }
}

function CommentReference({
  root,
  versionLabel,
}: {
  root: ResourceComment;
  versionLabel?: (versionId: string) => string | null;
}) {
  const context = readCommentContext(root);
  const version = context?.canvasVersionId
    ? versionLabel?.(context.canvasVersionId)
    : null;
  const anchor = context?.anchor;
  const quote = anchor?.kind === "text" ? anchor.quote : null;
  if (!version && !quote) return null;
  return (
    <span className="flex min-w-0 items-center gap-1.5 text-muted-foreground text-xs">
      {version && <span className="shrink-0">{version} ·</span>}
      {quote && (
        <span
          className="min-w-0 truncate border-[rgb(250_204_21)] border-l-2 pl-2"
          title={quote}
        >
          {quote}
        </span>
      )}
    </span>
  );
}

function commentResource(source: CommentSource): CommentResource {
  if (source.kind === "canvas") return { kind: "canvas", name: source.name };
  if (source.kind === "task") return { kind: "task", name: source.name };
  return { kind: "artifact", name: source.name };
}

function sendSourceCommentToAgent(
  taskId: string,
  source: CommentSource,
  root: ResourceComment | null,
  content: string,
): void {
  const resource = commentResource(source);
  sendCommentToAgent({
    taskId,
    comment: content,
    context: commentAgentContext(
      root ? (readCommentContext(root)?.anchor ?? null) : { kind: "document" },
      resource,
    ),
    surface: resource.kind,
  });
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
  commentVersionLabel,
}: {
  thread: TaskCommentThread;
  source: CommentSource;
  root: ResourceComment;
  taskId: string | null;
  members: UserBasic[];
  selected: boolean;
  pulsing: boolean;
  resolution?: HighlightResolution;
  onOpen: () => void;
  commentVersionLabel?: (versionId: string) => string | null;
}) {
  const createComment = useCreateComment(source.target, taskId ?? undefined);
  const setResolved = useSetCommentResolved(source.target);
  const rootPending = isOptimisticComment(root);

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
      source={
        <CommentReference root={root} versionLabel={commentVersionLabel} />
      }
      onSelect={onOpen}
      canReply={!rootPending}
      canResolve={!rootPending}
      onReply={async (content, mentions) => {
        await createComment.mutateAsync({
          content,
          sourceCommentId: root.id,
          context: readCommentContext(root) ?? { anchor: { kind: "document" } },
          mentions,
        });
      }}
      onResolve={async (resolved) => {
        await setResolved.mutateAsync({ root, resolved });
      }}
      onSendReplyToAgent={(content) =>
        sendSourceCommentToAgent(taskId, source, root, content)
      }
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
    try {
      if (!(await action())) throw new Error("GitHub comment action failed");
    } finally {
      setBusy(false);
    }
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
      source={
        origin.kind === "pr-review" && (
          <span
            className="block truncate text-muted-foreground text-xs"
            title={origin.filePath}
          >
            {origin.filePath.split("/").at(-1)}
          </span>
        )
      }
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
  taskId,
  task,
  timeline,
  onlySource,
  canvasVersionId,
  commentVersionLabel,
  onCanvasCommentOpen,
}: {
  taskId: string | null;
  task?: Task;
  timeline?: ThreadTimelineRow<TaskThreadMessage>[];
  /** Restricts the pane to one resource known by its host, without relying on
   * the task timeline to rediscover it. */
  onlySource?: CommentSource;
  canvasVersionId?: string | null;
  commentVersionLabel?: (versionId: string) => string | null;
  onCanvasCommentOpen?: (versionId: string | null) => void;
}) {
  const focusKey = onlySource
    ? commentTargetKey(onlySource.target)
    : (taskId ?? "");
  const { runs } = useTaskRuns(onlySource ? undefined : (taskId ?? undefined));
  const { members } = useOrgMembers();
  const openArtifactTab = usePanelLayoutStore((state) => state.openArtifactTab);
  const activeArtifactId = useActiveArtifactId(focusKey);
  const requestCommentFocus = useCommentNavigationStore(
    (state) => state.requestCommentFocus,
  );
  const focus = useCommentNavigationStore(
    (state) => state.focusByTask[focusKey],
  );
  const resolutionsByTarget = useCommentNavigationStore(
    (state) => state.resolutionsByTarget,
  );
  const [stateFilter, setStateFilter] = useState<CommentStateFilter>("open");
  const [sourceFilter, setSourceFilter] = useState<string>(ALL_SOURCES);
  const [pulseThreadId, setPulseThreadId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const threadListRef = useRef<HTMLDivElement>(null);
  const sourceFilterTouched = useRef(false);
  const previousFocusKey = useRef(focusKey);

  useEffect(() => {
    if (previousFocusKey.current === focusKey) return;
    previousFocusKey.current = focusKey;
    sourceFilterTouched.current = false;
    setSourceFilter(ALL_SOURCES);
    setDraft("");
  }, [focusKey]);

  const rows = useMemo(
    () => (task ? buildRows(task, timeline ?? [], runs) : []),
    [task, timeline, runs],
  );
  const sources = useMemo(
    () => (onlySource ? [onlySource] : commentSources(focusKey, rows)),
    [focusKey, rows, onlySource],
  );
  const targets = useMemo(
    () =>
      onlySource
        ? sources.map((source) => source.target)
        : [
            ...sources.slice(0, 1),
            ...sources.slice(1, MAX_RESOURCE_COMMENT_TARGETS + 1),
          ].map((source) => source.target),
    [onlySource, sources],
  );
  const singleSourceComments = useCommentsQuery(
    onlySource?.target ?? null,
    taskId ?? "",
  );
  const taskComments = useCommentsForTargetsQuery(
    onlySource ? [] : targets,
    focusKey,
    {
      live: true,
      intervalMs: POLL_INTERVAL_MS,
    },
  );
  const commentsQuery = onlySource ? singleSourceComments : taskComments;
  const prUrls = useMemo(
    () =>
      onlySource
        ? []
        : rows
            .flatMap((row) => (row.kind === "pr" ? [row.url] : []))
            .slice(0, MAX_PR_COMMENT_SOURCES),
    [rows, onlySource],
  );
  const prUrlsKey = prUrls.join("\n");
  const [prLoadProgress, setPrLoadProgress] = useState({
    key: "",
    count: MAX_CONCURRENT_PR_SOURCES,
  });
  const loadedPrSourceCount =
    prLoadProgress.key === prUrlsKey
      ? prLoadProgress.count
      : MAX_CONCURRENT_PR_SOURCES;
  const loadedPrUrls = prUrls.slice(0, loadedPrSourceCount);
  const prConversation = usePrCommentsForUrls(loadedPrUrls);
  const prReviews = usePrReviewThreadsForUrls(loadedPrUrls);
  const prTitles = usePrTitles(loadedPrUrls);
  useEffect(() => {
    if (
      prConversation.isLoading ||
      prReviews.isLoading ||
      loadedPrSourceCount >= prUrls.length
    ) {
      return;
    }
    setPrLoadProgress({
      key: prUrlsKey,
      count: Math.min(
        loadedPrSourceCount + MAX_CONCURRENT_PR_SOURCES,
        prUrls.length,
      ),
    });
  }, [
    loadedPrSourceCount,
    prConversation.isLoading,
    prReviews.isLoading,
    prUrlsKey,
    prUrls.length,
  ]);

  const taskTarget = useMemo(() => taskCommentTarget(focusKey), [focusKey]);
  const composerTarget = onlySource?.target ?? taskTarget;
  const createComment = useCreateComment(composerTarget, taskId ?? undefined);

  const threads = useMemo(() => {
    const reviewByUrl = new Map(prReviews.byUrl);
    const conversationByUrl = new Map(prConversation.byUrl);
    const resourceThreads = resourceCommentThreads(
      commentsQuery.data ?? EMPTY_COMMENTS,
      sources,
    );
    const prThreads = loadedPrUrls.flatMap((prUrl) =>
      prCommentThreads(
        prUrl,
        prTitles[prUrl] ?? `PR #${prUrl.split("/").at(-1)}`,
        reviewByUrl.get(prUrl) ?? [],
        conversationByUrl.get(prUrl) ?? [],
      ),
    );
    return [...resourceThreads, ...prThreads].sort(byNewestThread);
  }, [
    commentsQuery.data,
    sources,
    loadedPrUrls,
    prTitles,
    prReviews.byUrl,
    prConversation.byUrl,
  ]);

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
  const stateFilteredThreads = useMemo(
    () =>
      threads.filter(
        (thread) => thread.resolved === (stateFilter === "resolved"),
      ),
    [stateFilter, threads],
  );
  const sourceOptions = useMemo(
    () =>
      threadSourceOptions(stateFilteredThreads, [
        ...sources.map((source) => ({
          key: commentTargetKey(source.target),
          label: source.name,
          kind: source.kind,
        })),
        ...prUrls.map((prUrl) => ({
          key: prUrl,
          label: prTitles[prUrl] ?? `PR #${prUrl.split("/").at(-1)}`,
          kind: "pr" as const,
        })),
      ]),
    [prTitles, prUrls, sources, stateFilteredThreads],
  );
  const effectiveSourceFilter =
    sourceFilter === ALL_SOURCES || knownSourceKeys.has(sourceFilter)
      ? sourceFilter
      : ALL_SOURCES;
  const sourceLabel =
    effectiveSourceFilter === ALL_SOURCES
      ? "All sources"
      : (sourceOptions.find((option) => option.key === effectiveSourceFilter)
          ?.label ?? "All sources");

  // Follow the artifact on screen until the reader picks a source themselves;
  // after that the filter is theirs, not the pane's.
  useEffect(() => {
    if (onlySource || sourceFilterTouched.current) return;
    setSourceFilter(
      activeArtifactId
        ? commentTargetKey({ scope: "task_artifact", itemId: activeArtifactId })
        : ALL_SOURCES,
    );
  }, [activeArtifactId, onlySource]);

  const inSource = (thread: TaskCommentThread) =>
    effectiveSourceFilter === ALL_SOURCES ||
    thread.sourceKey === effectiveSourceFilter;
  const scoped = threads.filter(inSource);
  const openCount = scoped.filter((thread) => !thread.resolved).length;
  const resolvedCount = scoped.length - openCount;
  const visibleThreads = stateFilteredThreads.filter(inSource);

  const openThread = useCallback(
    (thread: TaskCommentThread, requestThreadFocus = true) => {
      const origin = thread.origin;
      if (origin.kind === "pr-review" || origin.kind === "pr-conversation") {
        openPrInReview(focusKey, origin.prUrl);
        if (origin.kind === "pr-review") {
          // The review pane scrolls by file; a specific comment is as close as it
          // gets until it grows a per-thread target.
          useReviewNavigationStore
            .getState()
            .requestScrollToFile(focusKey, origin.filePath);
        }
        return;
      }
      const { source, root } = origin;
      if (source.kind === "canvas") {
        if (requestThreadFocus) {
          requestCommentFocus(focusKey, source.target, root.id);
        }
        if (onCanvasCommentOpen) {
          onCanvasCommentOpen(
            readCommentContext(root)?.canvasVersionId ?? null,
          );
          return;
        }
        canvasArtifactOpenHandler(source.url)?.();
        return;
      }
      // A thread on the task itself has nowhere else to open because it lives here.
      if (source.kind === "task" || !source.runId) return;
      openArtifactTab(focusKey, {
        runId: source.runId,
        artifactId: source.target.itemId,
        name: source.name,
      });
      if (requestThreadFocus) {
        requestCommentFocus(focusKey, source.target, root.id);
      }
    },
    [onCanvasCommentOpen, openArtifactTab, requestCommentFocus, focusKey],
  );

  // A thread picked on the artifact itself has to surface here, even when a
  // filter is hiding it. Each request is honoured once, by nonce: resolving the
  // focused thread later must not drag the filters along with it.
  const focusedThreadId = focus?.threadId ?? null;
  const handledFocusRef = useRef<string | null>(null);
  useEffect(() => {
    const handledKey = focus ? `${focusKey}:${focus.nonce}` : null;
    if (!focus || handledFocusRef.current === handledKey) return;
    const focused = threads.find((thread) => thread.id === focus.threadId);
    // The thread may still be loading, so wait rather than guess its filters.
    if (!focused) return;
    handledFocusRef.current = handledKey;
    setStateFilter(focused.resolved ? "resolved" : "open");
    setSourceFilter((current) =>
      current === ALL_SOURCES || current === focused.sourceKey
        ? current
        : ALL_SOURCES,
    );
    setPulseThreadId(focus.threadId);
    if (focus.intent === "navigate") openThread(focused, false);
    if (focus.intent === "focus-only") return;
    requestAnimationFrame(() => {
      const pane = threadListRef.current;
      const thread = pane?.querySelector<HTMLElement>(
        `[data-comment-thread-id="${CSS.escape(focus.threadId)}"]`,
      );
      if (pane && thread) scrollThreadInPane(pane, thread);
    });
  }, [focus, openThread, threads, focusKey]);
  // The pulse fades on its own; owning the timer in its own effect keeps it
  // cleaned up on the next pulse or on unmount, without a stray ref.
  useEffect(() => {
    if (!pulseThreadId) return;
    const timer = setTimeout(() => setPulseThreadId(null), PULSE_MS);
    return () => clearTimeout(timer);
  }, [pulseThreadId]);

  const loading =
    commentsQuery.isLoading || prConversation.isLoading || prReviews.isLoading;
  const loadFailed =
    commentsQuery.isError || prConversation.isError || prReviews.isError;

  return (
    // The parent scrolls the middle; the filters and the composer are pinned so
    // they stay reachable however long the thread list grows.
    <div className="flex h-full min-h-0 flex-col">
      <CommentListHeader
        stateFilter={stateFilter}
        openCount={openCount}
        resolvedCount={resolvedCount}
        onStateFilterChange={setStateFilter}
        sourceFilter={
          onlySource
            ? undefined
            : {
                value: effectiveSourceFilter,
                valueLabel: sourceLabel,
                options: sourceOptions,
                onChange: (value) => {
                  sourceFilterTouched.current = value !== ALL_SOURCES;
                  setSourceFilter(value);
                },
              }
        }
      />
      <div ref={threadListRef} className="min-h-0 flex-1 overflow-y-auto">
        {loadFailed ? (
          <Empty className="py-8">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <ChatCircleIcon />
              </EmptyMedia>
              <EmptyTitle>Couldn't load comments</EmptyTitle>
              <EmptyDescription>
                Refresh the page to try again.
              </EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : loading && threads.length === 0 ? (
          <LoadingState className="py-8" />
        ) : visibleThreads.length === 0 ? (
          <Empty className="h-full border-0">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <ChatCircleIcon />
              </EmptyMedia>
              <EmptyTitle>
                No {stateFilter === "open" ? "open" : "resolved"} comments
              </EmptyTitle>
              <EmptyDescription>
                {stateFilter === "open"
                  ? onlySource
                    ? "Comment on this canvas to start a thread."
                    : "Comment on the task below, or open an artifact and select text to start a thread there."
                  : "Resolved threads will appear here."}
              </EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : (
          <CommentThreadGroups
            threads={visibleThreads}
            grouped={!onlySource}
            revealThreadId={pulseThreadId}
            renderThread={(thread) =>
              thread.origin.kind === "resource" ? (
                <ResourceThreadRow
                  key={thread.id}
                  thread={thread}
                  source={thread.origin.source}
                  root={thread.origin.root}
                  taskId={taskId}
                  members={members}
                  selected={thread.id === focusedThreadId}
                  pulsing={thread.id === pulseThreadId}
                  resolution={resolutionsByTarget[thread.sourceKey]?.get(
                    thread.id,
                  )}
                  onOpen={() => openThread(thread)}
                  commentVersionLabel={commentVersionLabel}
                />
              ) : (
                <PrThreadRow
                  key={thread.id}
                  thread={thread}
                  selected={thread.id === focusedThreadId}
                  pulsing={thread.id === pulseThreadId}
                  onOpen={() => openThread(thread)}
                />
              )
            }
          />
        )}
      </div>
      <footer className="sticky bottom-0 shrink-0 border-border border-t bg-background p-2">
        <CommentComposer
          value={draft}
          onValueChange={setDraft}
          onSubmit={async (content, mentions) => {
            const created = await createComment.mutateAsync({
              content,
              context: {
                anchor: { kind: "document" },
                ...(canvasVersionId ? { canvasVersionId } : {}),
              },
              mentions,
            });
            setDraft("");
            requestCommentFocus(focusKey, composerTarget, created.id, {
              intent: "focus-only",
            });
          }}
          members={members}
          placeholder={`Comment on this ${onlySource ? "canvas" : "task"}…`}
          rows={1}
          disabled={createComment.isPending}
          compact
          onSendToAgent={(content) =>
            sendSourceCommentToAgent(
              taskId,
              onlySource ?? {
                kind: "task",
                target: composerTarget,
                name: "This task",
              },
              null,
              content,
            )
          }
        />
      </footer>
    </div>
  );
}
