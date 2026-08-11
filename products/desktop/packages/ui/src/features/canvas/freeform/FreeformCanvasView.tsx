import {
  ArrowUUpLeftIcon,
  ArrowUUpRightIcon,
  ClockCounterClockwiseIcon,
  ShapesIcon,
  SidebarSimpleIcon,
  SpinnerGapIcon,
  WarningIcon,
} from "@phosphor-icons/react";
import {
  currentHeadBuildFailure,
  hasActiveCanvasBuild,
  historicalCanvasBuild,
  latestFinishedCanvasBuild,
  publishedCanvasBuild,
} from "@posthog/core/canvas/canvasBuildSchemas";
import {
  type CanvasAnalyticsConfig,
  type CanvasCommentHighlight,
  type CanvasTextSelection,
  limitCanvasCommentHighlights,
} from "@posthog/core/canvas/freeformSchemas";
import { useHostTRPC } from "@posthog/host-router/react";
import {
  Button,
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@posthog/quill";
import { CANVAS_COMPONENT_PATH } from "@posthog/shared";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import {
  isCanvasGenerating,
  isCanvasGenerationRunning,
} from "@posthog/ui/features/canvas/freeform/canvasGenerationStatus";
import { invalidateCanvasLifecycle } from "@posthog/ui/features/canvas/hooks/invalidateCanvasLifecycle";
import { useCanvasBuilds } from "@posthog/ui/features/canvas/hooks/useCanvasBuilds";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import {
  useCanvasSource,
  useCanvasVersions,
  useDashboardMutations,
} from "@posthog/ui/features/canvas/hooks/useDashboards";
import { useCanvasChatPanelStore } from "@posthog/ui/features/canvas/stores/canvasChatPanelStore";
import {
  dashboardIdOf,
  useFreeformChatStore,
  useFreeformThread,
} from "@posthog/ui/features/canvas/stores/freeformChatStore";
import type { EditorHandle } from "@posthog/ui/features/message-editor/types";
import { useCommentNavigationStore } from "@posthog/ui/features/sessions/commentNavigationStore";
import {
  buildCommentThreads,
  readCommentContext,
} from "@posthog/ui/features/sessions/components/commentViewTypes";
import { useCommentsQuery } from "@posthog/ui/features/sessions/components/useComments";
import { useSessionForTask } from "@posthog/ui/features/sessions/useSession";
import { taskDetailQuery } from "@posthog/ui/features/tasks/queries";
import { ResizableSidebar } from "@posthog/ui/primitives/ResizableSidebar";
import { toast } from "@posthog/ui/primitives/toast";
import { track } from "@posthog/ui/shell/analytics";
import {
  Box,
  Flex,
  Button as RadixButton,
  ScrollArea,
  Text,
  Tooltip,
} from "@radix-ui/themes";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { AnimatePresence, motion } from "framer-motion";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { BuiltCanvas } from "./BuiltCanvas";
import { CanvasBuildStatus } from "./CanvasBuildStatus";
import { CanvasFramePlaceholder } from "./CanvasFramePlaceholder";
import { CanvasGenerateHero } from "./CanvasGenerateHero";
import { CanvasPermissionDialog } from "./CanvasPermissionDialog";
import { CanvasSelectionCommentAction } from "./CanvasSelectionCommentAction";
import { CanvasSidePanel } from "./CanvasSidePanel";
import { canvasCommentTaskId } from "./canvasCommentTask";
import { canvasSidePanelVisibility } from "./canvasSidePanelVisibility";
import {
  canvasVersionNavigation,
  shouldClearCanvasBrowse,
} from "./canvasVersionNavigation";
import { handleFreeformDataRequest } from "./freeformDataBridge";
import { useCanvasNavigation } from "./useCanvasNavigation";
import { usePinnedArtifact } from "./usePinnedArtifact";

// A freeform (React-in-iframe) canvas. The rendered output is, in priority
// order: a historical version being browsed, the published build's
// artifact, or — before the first build lands — the head source client-rendered
// through the warm-frame pool when it's a single-file project. Edit mode adds
// the chat panel, version navigation (browse/revert over the server-side
// history), and an edit composer. Generation runs as a dedicated task; while
// one is in flight the empty canvas shows a "Generating…" state with the run's
// chat panel open by default (in view mode too), so the work is watchable.
// The canvas runtime error string is user/agent-authored and can carry source
// fragments, query results, or secrets. Reduce it to the leading error class name
// (e.g. "TypeError") for analytics, so no interpolated content crosses the boundary.
function canvasErrorType(message: string): string {
  return (
    message.match(/^([A-Z][A-Za-z0-9]*(?:Error|Exception))\b/)?.[1] ?? "unknown"
  );
}

export function FreeformCanvasView({
  threadId,
  interactive,
}: {
  threadId: string;
  interactive: boolean;
}) {
  const dashboardId = dashboardIdOf(threadId);
  const { runtimeError, browseVersionId } = useFreeformThread(threadId);
  const setBrowseVersion = useFreeformChatStore((s) => s.setBrowseVersion);
  const setRuntimeError = useFreeformChatStore((s) => s.setRuntimeError);

  // Right-hand panel state (persisted minimize + width). `startedTaskId` is a
  // local bridge so the composer floats to the side immediately on submit,
  // before the canvas record's polled generationTaskId catches up.
  const [startedTaskId, setStartedTaskId] = useState<string | null>(null);
  const [textSelection, setTextSelection] =
    useState<CanvasTextSelection | null>(null);
  const [clearTextSelectionKey, setClearTextSelectionKey] = useState(0);
  const dismissTextSelection = useCallback(() => {
    setTextSelection(null);
    setClearTextSelectionKey((key) => key + 1);
  }, []);
  const collapsed = useCanvasChatPanelStore((s) => s.collapsed);
  const panelViewOpen = useCanvasChatPanelStore((s) => s.viewOpen);
  const setCollapsed = useCanvasChatPanelStore((s) => s.setCollapsed);
  const panelWidth = useCanvasChatPanelStore((s) => s.width);
  const setPanelWidth = useCanvasChatPanelStore((s) => s.setWidth);
  const [isResizingPanel, setIsResizingPanel] = useState(false);
  // Set when a generation is kicked off from the hero, so the panel stays shut
  // (width 0) until the hero finishes sliding down (onExitComplete), then opens
  // — the sequenced slide-in. Every other path leaves it false, so the panel is
  // open from the start (no delay on cold load or minimize/expand).
  const [waitingForHeroExit, setWaitingForHeroExit] = useState(false);

  const trpc = useHostTRPC();
  const queryClient = useQueryClient();

  // The generation-task association lives in the canvas record's meta. Poll it
  // while a task is running so the fresh head version + the cleared association
  // show up without a manual refresh.
  const { data: dashboard, isLoading: dashboardLoading } = useQuery(
    trpc.dashboards.get.queryOptions(
      { id: dashboardId },
      { enabled: !!dashboardId, staleTime: 4000 },
    ),
  );
  const genTaskId = dashboard?.generationTaskId ?? null;
  const channelId = dashboard?.channelId ?? "";

  useEffect(() => {
    if (genTaskId) setStartedTaskId(null);
  }, [genTaskId]);

  // The run whose chat the panel shows: the record's id, or the optimistic
  // bridge until the poll catches up.
  const effectiveTaskId = genTaskId ?? startedTaskId;

  const { channels } = useChannels();
  const channelName = useMemo(
    () => channels.find((c) => c.id === channelId)?.name ?? "",
    [channels, channelId],
  );

  // Run status derivation (cloud vs local) lives in a pure, tested helper; a
  // terminal run record always ends "running" so a stale session can't strand
  // the canvas on "Generating".
  const { data: genTask, isLoading: genTaskLoading } = useQuery({
    ...taskDetailQuery(effectiveTaskId ?? ""),
    enabled: !!effectiveTaskId,
    refetchInterval: effectiveTaskId ? 5000 : false,
  });
  const genSession = useSessionForTask(effectiveTaskId ?? undefined);
  // Whether the run's session is still alive. Drives record + build polling so
  // a freshly published version and its queued build get picked up. A local ACP
  // session stays "connected" after its generation prompt finishes, so this
  // keeps syncing until it disconnects. Uses the shared, tested helper, which
  // also stops once the run record is terminal so a stale/stuck session can't
  // keep us polling forever.
  const isSyncing = isCanvasGenerationRunning({
    genTaskId: effectiveTaskId,
    genTaskLoading,
    latestRun: genTask?.latest_run,
    session: genSession,
  });
  // Whether the agent is actively producing the canvas right now. Drives the
  // "Generating…" UI (notice, composer, undo/redo). Shares the tested helper
  // with the completion-toast watcher so both read the same signal. Keys off
  // effectiveTaskId (genTaskId ?? startedTaskId), matching isSyncing above.
  const isGenerating = isCanvasGenerating({
    genTaskId: effectiveTaskId,
    genTaskLoading,
    latestRun: genTask?.latest_run,
    session: genSession,
  });

  // Poll the record while the session is alive so a just-published head version
  // appears (the publish lands while the prompt is still pending).
  useQuery(
    trpc.dashboards.get.queryOptions(
      { id: dashboardId },
      {
        enabled: !!dashboardId && isSyncing,
        refetchInterval: isSyncing ? 4000 : false,
      },
    ),
  );

  // When the run stops syncing, sweep the derived caches once: the agent's
  // publish queued a build server-side, so the record, lifecycle, versions,
  // and source must refresh promptly for the artifact swap even though
  // polling stops.
  const wasSyncingRef = useRef(isSyncing);
  useEffect(() => {
    if (wasSyncingRef.current && !isSyncing && dashboardId) {
      void invalidateCanvasLifecycle(queryClient, trpc, dashboardId);
    }
    wasSyncingRef.current = isSyncing;
  }, [isSyncing, dashboardId, queryClient, trpc]);

  // Build lifecycle, polled while a build is active or a generation is in
  // flight (the agent's publish queues the build server-side — without the
  // `generating` signal the client would never observe it start).
  const browsing = !!browseVersionId;
  const {
    lifecycle,
    isLoading: buildsLoading,
    dataUpdatedAt: buildsUpdatedAt,
  } = useCanvasBuilds(dashboardId, {
    generating: isSyncing,
    versionId: browsing ? (browseVersionId ?? undefined) : undefined,
  });
  const publishedBuild = lifecycle ? publishedCanvasBuild(lifecycle) : null;
  const historicalBuild =
    lifecycle && browseVersionId
      ? historicalCanvasBuild(lifecycle, browseVersionId)
      : null;

  // The published build's artifact, pinned to one signed URL per build (so the
  // 2s builds poll can't reload the iframe), with expired-URL recovery via the
  // refresh-key remount. The whole lifecycle machine lives in the hook.
  const {
    artifact: pinnedArtifact,
    refreshKey: artifactRefreshKey,
    onReady: onArtifactReady,
  } = usePinnedArtifact({
    dashboardId,
    publishedBuild,
    lifecycle,
    mintedAt: buildsUpdatedAt,
    suspended: browsing,
  });
  const {
    artifact: pinnedHistoricalArtifact,
    refreshKey: historicalArtifactRefreshKey,
    onReady: onHistoricalArtifactReady,
  } = usePinnedArtifact({
    dashboardId,
    publishedBuild: historicalBuild,
    lifecycle,
    mintedAt: buildsUpdatedAt,
    suspended: !browsing,
  });

  // Server-side version history (newest first), for the undo/redo navigation.
  const { versions, isLoading: versionsLoading } =
    useCanvasVersions(dashboardId);
  const commentTaskId = canvasCommentTaskId(genTaskId, versions);

  // Clear a browse that points at a version the history no longer contains
  // (e.g. it was pruned server-side while this canvas was open).
  useEffect(() => {
    if (
      shouldClearCanvasBrowse({ versions, versionsLoading, browseVersionId })
    ) {
      setBrowseVersion(threadId, null);
    }
  }, [browseVersionId, versions, versionsLoading, threadId, setBrowseVersion]);

  // Undo/redo step through the version list relative to the HEAD (which, after
  // a revert, may sit mid-list rather than at versions[0]). The arithmetic is
  // a tested pure helper; only the isGenerating gate is view-local.
  const nav = canvasVersionNavigation({
    versions,
    headVersionId: dashboard?.currentVersionId,
    browseVersionId: browsing ? browseVersionId : null,
  });
  const { currentIndex } = nav;
  const canUndo = !isGenerating && nav.canUndo;
  const canRedo = !isGenerating && nav.canRedo;
  const onUndo = () => {
    if (nav.undoTargetId) setBrowseVersion(threadId, nav.undoTargetId);
  };
  const onRedo = () => {
    // A null target means stepping onto (or past) the head — back to live.
    setBrowseVersion(threadId, nav.redoTargetId);
  };

  // Revert: make the browsed version the head. The mutation invalidates the
  // record, versions, source, and builds caches (the server queues a rebuild),
  // so afterwards only the local browse state needs clearing.
  const { revertToVersion, isReverting } = useDashboardMutations();
  const onRevert = useCallback(async () => {
    if (!browseVersionId) return;
    try {
      await revertToVersion(
        dashboardId,
        browseVersionId,
        dashboard?.currentVersionId ?? null,
      );
      setBrowseVersion(threadId, null);
    } catch (error) {
      toast.error("Couldn't revert canvas", {
        description: error instanceof Error ? error.message : String(error),
      });
    }
  }, [
    browseVersionId,
    dashboard?.currentVersionId,
    dashboardId,
    threadId,
    revertToVersion,
    setBrowseVersion,
  ]);

  // Head source, fetched only when there's no published artifact to render.
  // Migrated single-file canvases have no version pointer, but the source
  // endpoint exposes their stored code as a synthetic project.
  const headVersionId = dashboard?.currentVersionId ?? null;
  const displayedVersionId = browsing
    ? browseVersionId
    : (publishedBuild?.sourceVersionId ?? headVersionId);
  const commentTarget = useMemo(
    () => ({ scope: "desktop_canvas" as const, itemId: dashboardId }),
    [dashboardId],
  );
  const commentsQuery = useCommentsQuery(
    commentTaskId ? commentTarget : null,
    commentTaskId ?? "",
  );
  const focusedCommentId = useCommentNavigationStore(
    (state) => state.focusByTask[commentTaskId ?? ""]?.threadId ?? null,
  );
  const activateComment = useCallback(
    (id: string) => {
      if (!commentTaskId) return;
      useCanvasChatPanelStore.getState().openComments();
      useCommentNavigationStore
        .getState()
        .requestCommentFocus(commentTaskId, commentTarget, id, {
          intent: "reveal-thread",
        });
    },
    [commentTaskId, commentTarget],
  );
  const commentHighlights = useMemo<CanvasCommentHighlight[]>(() => {
    const threads = buildCommentThreads(commentsQuery.data ?? []);
    return limitCanvasCommentHighlights(
      threads.flatMap((thread) => {
        if (thread.resolved) return [];
        const context = readCommentContext(thread.root);
        if (
          context?.anchor.kind !== "text" ||
          (context.canvasVersionId &&
            context.canvasVersionId !== displayedVersionId)
        ) {
          return [];
        }
        return [
          {
            id: thread.root.id,
            active: thread.root.id === focusedCommentId,
            anchor: context.anchor,
          },
        ];
      }),
    );
  }, [commentsQuery.data, displayedVersionId, focusedCommentId]);
  const selectionVersionRef = useRef(displayedVersionId);
  useEffect(() => {
    if (selectionVersionRef.current === displayedVersionId) return;
    selectionVersionRef.current = displayedVersionId;
    dismissTextSelection();
  }, [displayedVersionId, dismissTextSelection]);
  const commentVersionLabel = useCallback(
    (versionId: string) => {
      const index = versions.findIndex((version) => version.id === versionId);
      return index === -1 ? null : `V${versions.length - index}`;
    },
    [versions],
  );
  const wantHeadSource =
    !!dashboard && lifecycle !== undefined && !publishedBuild;
  const { source: headSource, isLoading: headSourceLoading } = useCanvasSource({
    id: wantHeadSource ? dashboardId : undefined,
    versionId: headVersionId ?? undefined,
  });
  const headCode = headSource?.project.files[CANVAS_COMPONENT_PATH];

  const trpcCapture = trpc.canvasData.captureConfig.queryOptions(undefined, {
    staleTime: 5 * 60_000,
  });
  const { data: captureConfig } = useQuery(trpcCapture);
  const analytics: CanvasAnalyticsConfig | undefined = useMemo(
    () =>
      captureConfig
        ? {
            apiHost: captureConfig.apiHost,
            publicKey: captureConfig.publicKey,
            distinctId: captureConfig.distinctId,
            persist: false,
          }
        : undefined,
    [captureConfig],
  );

  // The data bridge is a pure function; the QueryClient (its read cache) is
  // injected here rather than resolved inside it. Deliberately independent of
  // the builds poll: a dependency on `publishedBuild` (fresh object — with a
  // fresh signed artifactUrl — every 2s refetch) would churn the warm-frame
  // pool, which assumes stable callbacks. View-mode capability gating happens
  // in BuiltCanvas via the `capabilities` prop below.
  const onDataRequest = useCallback(
    (method: string, payload: unknown) =>
      handleFreeformDataRequest(method, payload, queryClient),
    [queryClient],
  );

  // Dedupes the runtime-error capture without a store dependency: reading
  // runtimeError in the callbacks would change their identity on every
  // error set/clear, and the warm-frame pool assumes stable callbacks.
  const lastRuntimeErrorRef = useRef<string | null>(null);
  const canvasTrackProps = useMemo(
    () => ({
      channel_id: channelId || undefined,
      dashboard_id: dashboardId,
      build_id: pinnedArtifact?.buildId,
    }),
    [channelId, dashboardId, pinnedArtifact?.buildId],
  );
  const onError = useCallback(
    (message: string) => {
      if (message !== lastRuntimeErrorRef.current) {
        lastRuntimeErrorRef.current = message;
        track(ANALYTICS_EVENTS.CANVAS_RUNTIME_ERROR, {
          ...canvasTrackProps,
          error_type: canvasErrorType(message),
        });
      }
      setRuntimeError(threadId, message);
    },
    [threadId, setRuntimeError, canvasTrackProps],
  );
  const onRendered = useCallback(() => {
    // "rendered" is as good as "ready" as proof the pinned artifact URL loaded.
    onArtifactReady();
    lastRuntimeErrorRef.current = null;
    setRuntimeError(threadId, null);
    track(ANALYTICS_EVENTS.CANVAS_RENDERED, canvasTrackProps);
  }, [threadId, setRuntimeError, onArtifactReady, canvasTrackProps]);
  const clearHistoricalArtifactError = useCallback(() => {
    onHistoricalArtifactReady();
    setRuntimeError(threadId, null);
  }, [threadId, setRuntimeError, onHistoricalArtifactReady]);

  // Routes the canvas's allowlisted nav intents within this channel.
  const onNavigate = useCanvasNavigation(channelId);

  // The edit composer's editor handle, so self-repair can prefill it.
  const editorRef = useRef<EditorHandle>(null);
  // Reveal the panel composer and prefill it. The panel stays mounted while
  // collapsed, so the editor handle is available even from a minimized panel.
  const prefillComposer = useCallback(
    (message: string) => {
      setCollapsed(false);
      editorRef.current?.setContent(message);
      editorRef.current?.focus();
    },
    [setCollapsed],
  );
  const askAgentToFix = () => {
    if (!runtimeError) return;
    prefillComposer(
      `The app threw a runtime error: "${runtimeError}". Fix it and rewrite the whole file.`,
    );
  };

  // The canvas "has content" once any source version exists or a build is
  // published — the record is the always-available signal, so a canvas with
  // content never flashes the empty state while source/builds load.
  const hasSource = !!headVersionId || !!headCode?.trim();
  const hasContent = hasSource || !!pinnedArtifact;
  // `isGenerating` keys off the effective task (the optimistic bridge right after
  // submit, then the polled record) and short-circuits on a terminal run — so a
  // failed/cancelled run can't strand the canvas body on the spinner.
  // The empty-canvas landing: a centered composer with suggestions. Held back
  // until the record settles (so it doesn't flash over a canvas that has content)
  // and only when no run is in flight. After submit it floats into the panel.
  const showHero =
    interactive &&
    !hasContent &&
    !effectiveTaskId &&
    !dashboardLoading &&
    !buildsLoading &&
    !headSourceLoading;
  // While a generation runs on a not-yet-renderable canvas, the run's chat is
  // the only meaningful content — open the side panel by default, in view mode
  // too, instead of stranding the user on the "Generating…" spinner. Dismissal
  // is local (not the persisted collapse) so landing on a generating canvas
  // always starts open, while a minimize still sticks for this visit.
  const [generatingPanelDismissed, setGeneratingPanelDismissed] =
    useState(false);
  useEffect(() => {
    if (effectiveTaskId) setGeneratingPanelDismissed(false);
  }, [effectiveTaskId]);
  const generatingPanelOpen =
    isGenerating &&
    !!effectiveTaskId &&
    !pinnedArtifact &&
    !headCode &&
    !generatingPanelDismissed;
  // The side panel exists once there's a canvas or an active run (edit mode),
  // while the generating default holds (any mode), or once it was opened from
  // view mode — a tested pure helper.
  const panelVisibility = canvasSidePanelVisibility({
    interactive,
    hasContent,
    hasActiveTask: !!effectiveTaskId,
    generatingPanelOpen,
    viewOpen: panelViewOpen,
    collapsed,
    hasCommentTask: !!commentTaskId,
  });
  const showPanel = panelVisibility.editing;
  // Build failures/progress surface in view mode too — the toolbar renders
  // there only while it has something to say.
  const hasBuildSignal =
    !!lifecycle &&
    lifecycle.builds.length > 0 &&
    (hasActiveCanvasBuild(lifecycle) ||
      !!currentHeadBuildFailure(lifecycle) ||
      latestFinishedCanvasBuild(lifecycle)?.buildStatus === "failed");
  const showToolbar = interactive || hasBuildSignal;

  return (
    <Flex height="100%" overflow="hidden" position="relative">
      {/* When the embedded chat isn't visible — panel minimized, or still shut
          mid-slide-in (waitingForHeroExit) — a paused tool-permission request
          would have nowhere to go, so surface it as a modal. When the panel is
          open, the chat handles it. */}
      {interactive &&
        effectiveTaskId &&
        ((collapsed && !generatingPanelOpen) || waitingForHeroExit) && (
          <CanvasPermissionDialog taskId={effectiveTaskId} />
        )}
      <Flex
        direction="column"
        className="min-w-0 flex-1 bg-gray-1"
        overflow="hidden"
      >
        {showToolbar && (
          <Flex
            align="center"
            justify="between"
            className="h-10 shrink-0 items-center border-b bg-chrome px-3"
          >
            <Flex align="center" gap="1">
              {interactive && (
                <>
                  <Button
                    size="icon"
                    variant="default"
                    aria-label="Undo"
                    disabled={!canUndo}
                    onClick={onUndo}
                  >
                    <ArrowUUpLeftIcon size={16} />
                  </Button>
                  <Button
                    size="icon"
                    variant="default"
                    aria-label="Redo"
                    disabled={!canRedo}
                    onClick={onRedo}
                  >
                    <ArrowUUpRightIcon size={16} />
                  </Button>
                  {versions.length > 0 && (
                    <Text size="1" className="ml-1 text-gray-9">
                      v{versions.length - currentIndex}/{versions.length}
                    </Text>
                  )}
                  {browsing && (
                    <Button
                      size="sm"
                      variant="primary"
                      className="ml-1"
                      disabled={isReverting}
                      onClick={() => void onRevert()}
                    >
                      {isReverting ? "Reverting…" : "Revert to this version"}
                    </Button>
                  )}
                </>
              )}
            </Flex>
            <Flex align="center" gap="2">
              <CanvasBuildStatus
                dashboardId={dashboardId}
                lifecycle={lifecycle}
                onAskAgentToFix={interactive ? prefillComposer : undefined}
              />
              {interactive &&
                (isGenerating && effectiveTaskId ? (
                  <>
                    <SpinnerGapIcon
                      size={14}
                      className="animate-spin text-accent-9"
                    />
                    <Text size="1" className="text-gray-10">
                      Generating
                    </Text>
                    <RadixButton size="1" variant="soft" asChild>
                      <Link
                        to="/website/$channelId/tasks/$taskId"
                        params={{ channelId, taskId: effectiveTaskId }}
                      >
                        View task
                      </Link>
                    </RadixButton>
                  </>
                ) : (
                  runtimeError && (
                    <>
                      <Flex align="center" gap="1" className="text-red-11">
                        <WarningIcon size={14} />
                        <Text size="1">Runtime error</Text>
                      </Flex>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={askAgentToFix}
                      >
                        Ask agent to fix
                      </Button>
                    </>
                  )
                ))}
              {interactive &&
                showPanel &&
                collapsed &&
                !generatingPanelOpen && (
                  <Tooltip
                    content={effectiveTaskId ? "Show chat" : "Edit canvas"}
                  >
                    <Button
                      size="icon"
                      variant="default"
                      aria-label="Show panel"
                      onClick={() => setCollapsed(false)}
                    >
                      <SidebarSimpleIcon size={16} />
                    </Button>
                  </Tooltip>
                )}
            </Flex>
          </Flex>
        )}

        <Box position="relative" className="min-h-0 flex-1">
          {/* Swooping accent bar across the top while a generation task runs. */}
          <div
            aria-hidden
            className={
              isGenerating
                ? "quill-section-loading quill-section-loading--active"
                : "quill-section-loading"
            }
          />
          {browsing ? (
            pinnedHistoricalArtifact ? (
              <Flex direction="column" className="h-full">
                <Flex
                  align="center"
                  justify="between"
                  className="shrink-0 border-b bg-accent-2 px-3 py-1.5"
                >
                  <Flex align="center" gap="1" className="text-accent-11">
                    <ClockCounterClockwiseIcon size={14} />
                    <Text size="1">Viewing a previous version</Text>
                  </Flex>
                  <Flex align="center" gap="2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setBrowseVersion(threadId, null)}
                    >
                      Back to latest
                    </Button>
                    {interactive && (
                      <Button
                        size="sm"
                        variant="primary"
                        disabled={isReverting}
                        onClick={() => void onRevert()}
                      >
                        {isReverting ? "Reverting…" : "Revert"}
                      </Button>
                    )}
                  </Flex>
                </Flex>
                <Box className="min-h-0 flex-1">
                  <BuiltCanvas
                    key={`${pinnedHistoricalArtifact.buildId}:${historicalArtifactRefreshKey}`}
                    artifactUrl={pinnedHistoricalArtifact.url}
                    capabilities={historicalBuild?.manifest?.capabilities}
                    onDataRequest={onDataRequest}
                    onError={onError}
                    onReady={clearHistoricalArtifactError}
                    onRendered={clearHistoricalArtifactError}
                    onNavigate={onNavigate}
                    onTextSelection={setTextSelection}
                    onCommentActivate={activateComment}
                    commentHighlights={commentHighlights}
                    clearTextSelectionKey={clearTextSelectionKey}
                  />
                </Box>
              </Flex>
            ) : buildsLoading ? (
              <ScrollArea className="h-full">
                <LoadingState />
              </ScrollArea>
            ) : (
              <ScrollArea className="h-full">
                <Empty className="h-full border-0">
                  <EmptyHeader>
                    <EmptyMedia variant="icon">
                      <ClockCounterClockwiseIcon size={24} />
                    </EmptyMedia>
                    <EmptyTitle>Preview unavailable</EmptyTitle>
                    <EmptyDescription>
                      {interactive
                        ? "This version does not have a saved preview. Revert to rebuild and view it."
                        : "This version does not have a saved preview. Go back to the latest version to continue."}
                    </EmptyDescription>
                  </EmptyHeader>
                  <EmptyContent>
                    <Flex align="center" gap="2">
                      {interactive && (
                        <Button
                          variant="primary"
                          size="default"
                          disabled={isReverting}
                          onClick={() => void onRevert()}
                        >
                          {isReverting
                            ? "Reverting…"
                            : "Revert to this version"}
                        </Button>
                      )}
                      <Button
                        variant="outline"
                        size="default"
                        onClick={() => setBrowseVersion(threadId, null)}
                      >
                        Back to latest
                      </Button>
                    </Flex>
                  </EmptyContent>
                </Empty>
              </ScrollArea>
            )
          ) : pinnedArtifact ? (
            <Box className="h-full w-full">
              <BuiltCanvas
                key={`${pinnedArtifact.buildId}:${artifactRefreshKey}`}
                artifactUrl={pinnedArtifact.url}
                capabilities={publishedBuild?.manifest?.capabilities}
                onDataRequest={onDataRequest}
                onError={onError}
                onReady={onArtifactReady}
                onRendered={onRendered}
                onNavigate={onNavigate}
                onTextSelection={setTextSelection}
                onCommentActivate={activateComment}
                commentHighlights={commentHighlights}
                clearTextSelectionKey={clearTextSelectionKey}
              />
            </Box>
          ) : headCode ? (
            // The iframe lives in the persistent warm-frame pool
            // (CanvasFrameHost); this placeholder just reserves the viewport
            // box and owns scroll via the host's overlay, so the canvas
            // survives navigation without a reload.
            <Box className="h-full w-full">
              <CanvasFramePlaceholder
                dashboardId={dashboardId}
                code={headCode}
                analytics={analytics}
                onDataRequest={onDataRequest}
                onError={onError}
                onRendered={onRendered}
                onNavigate={onNavigate}
                onTextSelection={setTextSelection}
                onCommentActivate={activateComment}
                commentHighlights={commentHighlights}
                clearTextSelectionKey={clearTextSelectionKey}
              />
            </Box>
          ) : (
            <ScrollArea className="h-full">
              {isGenerating ? (
                <GeneratingState
                  channelId={channelId}
                  taskId={effectiveTaskId ?? ""}
                />
              ) : dashboardLoading || buildsLoading || headSourceLoading ? (
                <LoadingState />
              ) : hasSource ? (
                // Source exists but nothing is renderable yet: a multi-file
                // project whose build hasn't succeeded. The toolbar's build
                // status carries the queued/failed detail.
                <Empty className="h-full border-0">
                  <EmptyHeader>
                    <EmptyMedia variant="icon">
                      <ShapesIcon size={24} />
                    </EmptyMedia>
                    <EmptyTitle>Waiting for build</EmptyTitle>
                    <EmptyDescription>
                      This canvas renders once its build completes — check the
                      build status in the toolbar.
                    </EmptyDescription>
                  </EmptyHeader>
                </Empty>
              ) : (
                <Empty className="h-full border-0">
                  <EmptyHeader>
                    <EmptyMedia variant="icon">
                      <ShapesIcon size={24} />
                    </EmptyMedia>
                    <EmptyTitle>Freeform canvas</EmptyTitle>
                    <EmptyDescription>
                      This canvas is empty. Hit Edit to build it with an agent.
                    </EmptyDescription>
                  </EmptyHeader>
                </Empty>
              )}
            </ScrollArea>
          )}
        </Box>
      </Flex>

      {(panelVisibility.editing || panelVisibility.viewing) && (
        <ResizableSidebar
          open={(!collapsed || generatingPanelOpen) && !waitingForHeroExit}
          width={panelWidth}
          setWidth={setPanelWidth}
          isResizing={isResizingPanel}
          setIsResizing={setIsResizingPanel}
          side="right"
        >
          {/* Kept mounted while collapsed (the sidebar hides it via width:0 +
              overflow:hidden) so the embedded run's session — and its activity
              heartbeat — stays alive and chat scroll survives a minimize. */}
          <CanvasSidePanel
            effectiveTaskId={effectiveTaskId}
            commentTaskId={commentTaskId}
            interactive={interactive}
            onMinimize={() => {
              setCollapsed(true);
              setGeneratingPanelDismissed(true);
            }}
            dashboardId={dashboardId}
            channelId={channelId}
            channelName={channelName}
            name={dashboard?.name ?? "Canvas"}
            displayedVersionId={displayedVersionId}
            commentVersionLabel={commentVersionLabel}
            onCommentOpen={(versionId) => {
              setBrowseVersion(
                threadId,
                versionId && versionId !== headVersionId ? versionId : null,
              );
            }}
            templateId={dashboard?.templateId}
            isEdit={hasSource}
            editorRef={editorRef}
            onStarted={setStartedTaskId}
          />
        </ResizableSidebar>
      )}

      <CanvasSelectionCommentAction
        selection={textSelection}
        taskId={commentTaskId}
        dashboardId={dashboardId}
        canvasName={dashboard?.name ?? "Canvas"}
        versionId={displayedVersionId}
        onDismiss={dismissTextSelection}
      />

      {/* The empty-canvas landing: a centered composer with suggestions,
          overlaying the canvas area. On submit it slides down; once it's gone
          (onExitComplete) the side panel slides in from the right. */}
      <AnimatePresence onExitComplete={() => setWaitingForHeroExit(false)}>
        {showHero && (
          <motion.div
            key="canvas-hero"
            initial={false}
            exit={{ y: "100%", opacity: 0 }}
            transition={{ duration: 0.32, ease: [0.4, 0, 0.2, 1] }}
            className="absolute inset-0 z-20 bg-gray-1"
          >
            <CanvasGenerateHero
              dashboardId={dashboardId}
              channelId={channelId}
              channelName={channelName}
              name={dashboard?.name ?? "Canvas"}
              templateId={dashboard?.templateId}
              onStarted={(id) => {
                // Hold the panel shut until the hero finishes sliding down.
                setWaitingForHeroExit(true);
                setStartedTaskId(id);
              }}
            />
          </motion.div>
        )}
      </AnimatePresence>
    </Flex>
  );
}

// Shown while the canvas record is still loading, so a canvas that actually has
// content doesn't flash the empty state before its source/builds resolve.
function LoadingState() {
  return (
    <Empty className="h-full">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <SpinnerGapIcon size={18} className="animate-spin text-accent-9" />
        </EmptyMedia>
        <EmptyTitle>Loading canvas</EmptyTitle>
      </EmptyHeader>
    </Empty>
  );
}

// Centered status shown while a generation task runs on an empty canvas, with a
// button to jump to the task doing the work.
function GeneratingState({
  channelId,
  taskId,
}: {
  channelId: string;
  taskId: string;
}) {
  return (
    <Empty className="h-full border-0">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <SpinnerGapIcon size={18} className="animate-spin text-accent-9" />
        </EmptyMedia>
        <EmptyTitle>Generating</EmptyTitle>
        <EmptyDescription>An agent is building this canvas.</EmptyDescription>
      </EmptyHeader>
      {taskId && (
        <EmptyContent>
          <Button
            variant="primary"
            size="default"
            render={
              <Link
                to="/website/$channelId/tasks/$taskId"
                params={{ channelId, taskId }}
              />
            }
          >
            View task
          </Button>
        </EmptyContent>
      )}
    </Empty>
  );
}
