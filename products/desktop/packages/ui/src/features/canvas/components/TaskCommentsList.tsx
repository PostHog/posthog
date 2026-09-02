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
  taskCommentTarget,
} from "@posthog/ui/features/canvas/components/taskArtifactRows";
import {
  byNewestThread,
  prCommentThreads,
  resourceCommentThreads,
  type SourceKind,
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
import { FileIcon } from "@posthog/ui/primitives/FileIcon";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

const EMPTY_COMMENTS: ResourceComment[] = [];
/** The whole task's threads in one request; slower than a single artifact's own
 *  poll because this one fans out across every resource. */
const POLL_INTERVAL_MS = 30_000;
const PULSE_MS = 1_200;
const ALL_SOURCES = "all";
// Keep task comments live, but bound the artifact and canvas poll so generated
// output cannot turn one Comments tab into an unbounded backend request.
const MAX_RESOURCE_COMMENT_TARGETS = 20;
// Each PR starts three GitHub-backed queries. Keep this cap at the source so a
// task with generated output cannot fan out into an unbounded number of requests.
const MAX_PR_COMMENT_SOURCES = 20;
const MAX_CONCURRENT_PR_SOURCES = 4;

type StateFilter = "open" | "resolved";

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
    <span className="mb-1 flex min-w-0 items-center gap-1.5 text-muted-foreground text-xs">
      {version && <span className="shrink-0">{version} ·</span>}
      {quote && (
        <span className="min-w-0 truncate" title={quote}>
          “{quote}”
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
  showSource = true,
  commentVersionLabel,
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
  showSource?: boolean;
  commentVersionLabel?: (versionId: string) => string | null;
}) {
  const createComment = useCreateComment(source.target, taskId);
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
        <>
          {showSource && <SourceLabel thread={thread} />}
          <CommentReference root={root} versionLabel={commentVersionLabel} />
        </>
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
  onlySource,
  canvasVersionId,
  commentVersionLabel,
  onCanvasCommentOpen,
}: {
  task: Task;
  timeline: ThreadTimelineRow<TaskThreadMessage>[];
  /** Restricts the pane to one resource known by its host, without relying on
   * the task timeline to rediscover it. */
  onlySource?: CommentSource;
  canvasVersionId?: string | null;
  commentVersionLabel?: (versionId: string) => string | null;
  onCanvasCommentOpen?: (versionId: string | null) => void;
}) {
  const { runs } = useTaskRuns(onlySource ? undefined : task.id);
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
  const threadListRef = useRef<HTMLDivElement>(null);
  const sourceFilterTouched = useRef(false);
  const previousTaskId = useRef(task.id);

  useEffect(() => {
    if (previousTaskId.current === task.id) return;
    previousTaskId.current = task.id;
    sourceFilterTouched.current = false;
    setSourceFilter(ALL_SOURCES);
    setDraft("");
  }, [task.id]);

  const rows = useMemo(
    () => buildRows(task, timeline, runs),
    [task, timeline, runs],
  );
  const sources = useMemo(
    () => (onlySource ? [onlySource] : commentSources(task.id, rows)),
    [task.id, rows, onlySource],
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
    task.id,
  );
  const taskComments = useCommentsForTargetsQuery(
    onlySource ? [] : targets,
    task.id,
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

  const taskTarget = useMemo(() => taskCommentTarget(task.id), [task.id]);
  const composerTarget = onlySource?.target ?? taskTarget;
  const createComment = useCreateComment(composerTarget, task.id);

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
        if (requestThreadFocus) {
          requestCommentFocus(task.id, source.target, root.id);
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
      openArtifactTab(task.id, {
        runId: source.runId,
        artifactId: source.target.itemId,
        name: source.name,
      });
      if (requestThreadFocus) {
        requestCommentFocus(task.id, source.target, root.id);
      }
    },
    [onCanvasCommentOpen, openArtifactTab, requestCommentFocus, task.id],
  );

  // A thread picked on the artifact itself has to surface here, even when a
  // filter is hiding it. Each request is honoured once, by nonce: resolving the
  // focused thread later must not drag the filters along with it.
  const focusedThreadId = focus?.threadId ?? null;
  const handledFocusRef = useRef<string | null>(null);
  useEffect(() => {
    const focusKey = focus ? `${task.id}:${focus.nonce}` : null;
    if (!focus || handledFocusRef.current === focusKey) return;
    const focused = threads.find((thread) => thread.id === focus.threadId);
    // The thread may still be loading, so wait rather than guess its filters.
    if (!focused) return;
    handledFocusRef.current = focusKey;
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
  }, [focus, openThread, threads, task.id]);
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
      <header className="sticky top-0 z-10 flex shrink-0 items-center justify-end gap-1 bg-gray-1 px-2 py-2">
        {!onlySource && (
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
                  sourceFilterTouched.current = value !== ALL_SOURCES;
                  setSourceFilter(value);
                }}
              >
                <DropdownMenuRadioItem value={ALL_SOURCES} className="gap-2">
                  <FunnelSimpleIcon
                    size={12}
                    className="shrink-0 text-gray-11"
                  />
                  <span className="min-w-0 truncate">All sources</span>
                  <span className="ml-auto shrink-0 pl-3 text-muted-foreground tabular-nums">
                    {stateFilteredThreads.length}
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
                      {option.count}
                    </span>
                  </DropdownMenuRadioItem>
                ))}
              </DropdownMenuRadioGroup>
            </DropdownMenuContent>
          </DropdownMenu>
        )}
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
      <div
        ref={threadListRef}
        className="min-h-0 flex-1 space-y-2 overflow-y-auto px-2 pt-3 pb-2"
      >
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
          <div className="flex justify-center py-8">
            <Spinner />
          </div>
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
                showSource={!onlySource}
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
            ),
          )
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
            requestCommentFocus(task.id, composerTarget, created.id, {
              intent: "focus-only",
            });
          }}
          members={members}
          placeholder={`Comment on this ${onlySource ? "canvas" : "task"}… Type @ to mention someone`}
          rows={2}
          disabled={createComment.isPending}
        />
      </footer>
    </div>
  );
}
