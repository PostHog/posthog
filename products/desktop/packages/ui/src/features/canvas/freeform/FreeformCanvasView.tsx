import {
  ArrowCounterClockwiseIcon,
  ArrowUUpLeftIcon,
  ArrowUUpRightIcon,
  ClockCounterClockwiseIcon,
  ShapesIcon,
  SidebarSimpleIcon,
  SpinnerGapIcon,
  WarningIcon,
} from "@phosphor-icons/react";
import {
  hasActiveCanvasBuild,
  latestFinishedCanvasBuild,
  publishedCanvasBuild,
} from "@posthog/core/canvas/canvasBuildSchemas";
import { assertCanvasCapability } from "@posthog/core/canvas/canvasCapabilities";
import type { CanvasAnalyticsConfig } from "@posthog/core/canvas/freeformSchemas";
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
import {
  isCanvasGenerating,
  isCanvasGenerationRunning,
} from "@posthog/ui/features/canvas/freeform/canvasGenerationStatus";
import { useCanvasBuilds } from "@posthog/ui/features/canvas/hooks/useCanvasBuilds";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import {
  useCanvasSource,
  useCanvasVersions,
  useDashboardMutations,
} from "@posthog/ui/features/canvas/hooks/useDashboards";
import { useCanvasChatPanelStore } from "@posthog/ui/features/canvas/stores/canvasChatPanelStore";
import {
  useFreeformChatStore,
  useFreeformThread,
} from "@posthog/ui/features/canvas/stores/freeformChatStore";
import type { EditorHandle } from "@posthog/ui/features/message-editor/types";
import { useSessionForTask } from "@posthog/ui/features/sessions/useSession";
import { taskDetailQuery } from "@posthog/ui/features/tasks/queries";
import { ResizableSidebar } from "@posthog/ui/primitives/ResizableSidebar";
import { toast } from "@posthog/ui/primitives/toast";
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
import { CanvasSidePanel } from "./CanvasSidePanel";
import { handleFreeformDataRequest } from "./freeformDataBridge";
import { useCanvasNavigation, useHomeCanvasReset } from "./useHomeCanvasView";

// The dashboardId a thread is keyed on ("dashboard:<id>" → "<id>").
function dashboardIdOf(threadId: string): string {
  return threadId.replace(/^dashboard:/, "");
}

// How long a mounted artifact iframe gets to post "ready"/"rendered" before
// its signed URL is suspected expired.
const ARTIFACT_READY_GRACE_MS = 15_000;
// Signed artifact URLs live ~60 minutes; below this age a load failure is a
// canvas bug, not an expired URL, so no refresh is attempted.
const ARTIFACT_URL_FRESH_MS = 50 * 60_000;

// The published build's artifact, pinned to a single signed URL. Every builds
// refetch mints a fresh URL for the same artifact, so rendering the lifecycle
// value directly would reload the iframe every 2s poll while a build runs.
interface PinnedArtifact {
  buildId: string;
  url: string;
  /** Epoch ms the pinned URL was minted (the builds fetch that produced it). */
  mintedAt: number;
}

// A freeform (React-in-iframe) canvas. The rendered output is, in priority
// order: a historical version being browsed (edit mode), the published build's
// artifact, or — before the first build lands — the head source client-rendered
// through the warm-frame pool when it's a single-file project. Edit mode adds
// the chat panel, version navigation (browse/revert over the server-side
// history), and an edit composer. Generation runs as a dedicated task; while
// one is in flight the empty canvas shows a "Generating… View task" state.
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
  const collapsed = useCanvasChatPanelStore((s) => s.collapsed);
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

  // Reconcile the optimistic bridge against the polled record during render
  // (not via an effect, which would flash a stale frame): once the record
  // reports its own generationTaskId, drop the bridge so the panel reverts to
  // the composer when the run later clears the association.
  const [prevGenTaskId, setPrevGenTaskId] = useState(genTaskId);
  if (genTaskId !== prevGenTaskId) {
    setPrevGenTaskId(genTaskId);
    if (genTaskId) setStartedTaskId(null);
  }

  // The run whose chat the panel shows: the record's id, or the optimistic
  // bridge until the poll catches up.
  const effectiveTaskId = genTaskId ?? startedTaskId;

  const { channels } = useChannels();
  const channelName = useMemo(
    () => channels.find((c) => c.id === channelId)?.name ?? "",
    [channels, channelId],
  );

  // The "Reset to default" affordance, shown only on a channel's home canvas.
  const {
    isHomeCanvas,
    isResetting,
    reset: onResetToDefault,
  } = useHomeCanvasReset({ channelId, dashboardId, threadId });

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
  // publish queued a build server-side, so the lifecycle (and version list)
  // must refresh promptly for the artifact swap even though polling stops.
  const wasSyncingRef = useRef(isSyncing);
  useEffect(() => {
    if (wasSyncingRef.current && !isSyncing && dashboardId) {
      void queryClient.invalidateQueries({
        queryKey: trpc.dashboards.builds.queryKey({ id: dashboardId }),
      });
      void queryClient.invalidateQueries({
        queryKey: trpc.dashboards.get.queryKey({ id: dashboardId }),
      });
      void queryClient.invalidateQueries({
        queryKey: trpc.dashboards.versions.queryKey({ id: dashboardId }),
      });
    }
    wasSyncingRef.current = isSyncing;
  }, [isSyncing, dashboardId, queryClient, trpc]);

  // Build lifecycle, polled while a build is active or a generation is in
  // flight (the agent's publish queues the build server-side — without the
  // `generating` signal the client would never observe it start).
  const {
    lifecycle,
    isLoading: buildsLoading,
    dataUpdatedAt: buildsUpdatedAt,
  } = useCanvasBuilds(dashboardId, { generating: isSyncing });
  const publishedBuild = lifecycle ? publishedCanvasBuild(lifecycle) : null;

  // Pin the artifact to one signed URL per build: every lifecycle refetch mints
  // a fresh URL for the same artifact, and adopting each one would reload the
  // iframe on every 2s poll while a build runs. Adopt only when the published
  // build itself changes — or when a refresh was explicitly requested because
  // the pinned URL expired. Adjusted during render (not an effect) so the swap
  // can't flash a stale frame.
  const [pinnedArtifact, setPinnedArtifact] = useState<PinnedArtifact | null>(
    null,
  );
  const wantFreshArtifactUrlRef = useRef(false);
  if (publishedBuild?.artifactUrl) {
    const shouldAdopt =
      !pinnedArtifact ||
      pinnedArtifact.buildId !== publishedBuild.id ||
      (wantFreshArtifactUrlRef.current &&
        pinnedArtifact.url !== publishedBuild.artifactUrl);
    if (shouldAdopt) {
      wantFreshArtifactUrlRef.current = false;
      setPinnedArtifact({
        buildId: publishedBuild.id,
        url: publishedBuild.artifactUrl,
        mintedAt: buildsUpdatedAt || Date.now(),
      });
    }
  } else if (lifecycle && pinnedArtifact) {
    // The lifecycle says there's no published build anymore — drop the pin.
    setPinnedArtifact(null);
  }

  // Expired-URL recovery: if the mounted artifact never posts "ready" or
  // "rendered" within the grace window AND the pinned URL is old enough to
  // have expired, refetch the lifecycle (minting a fresh URL) and adopt it.
  const artifactLoadedRef = useRef(false);
  const onArtifactReady = useCallback(() => {
    artifactLoadedRef.current = true;
  }, []);
  const browsing = interactive && !!browseVersionId;
  const renderedArtifact = !browsing ? pinnedArtifact : null;
  useEffect(() => {
    if (!renderedArtifact) return;
    artifactLoadedRef.current = false;
    const timer = setTimeout(() => {
      if (artifactLoadedRef.current) return;
      if (Date.now() - renderedArtifact.mintedAt < ARTIFACT_URL_FRESH_MS) {
        return;
      }
      wantFreshArtifactUrlRef.current = true;
      void queryClient.invalidateQueries({
        queryKey: trpc.dashboards.builds.queryKey({ id: dashboardId }),
      });
    }, ARTIFACT_READY_GRACE_MS);
    return () => clearTimeout(timer);
  }, [renderedArtifact, dashboardId, queryClient, trpc]);

  // Server-side version history (newest first), for the undo/redo navigation.
  const { versions, isLoading: versionsLoading } = useCanvasVersions(
    interactive ? dashboardId : undefined,
  );

  // Clear a browse that points at a version the history no longer contains
  // (e.g. it was pruned server-side while this canvas was open).
  useEffect(() => {
    if (
      browseVersionId &&
      !versionsLoading &&
      versions.length > 0 &&
      !versions.some((v) => v.id === browseVersionId)
    ) {
      setBrowseVersion(threadId, null);
    }
  }, [browseVersionId, versions, versionsLoading, threadId, setBrowseVersion]);

  // Undo/redo step through the version list relative to the HEAD (which, after
  // a revert, may sit mid-list rather than at versions[0]).
  const headIndex = useMemo(() => {
    const headId = dashboard?.currentVersionId;
    if (!headId) return 0;
    const idx = versions.findIndex((v) => v.id === headId);
    return idx === -1 ? 0 : idx;
  }, [dashboard?.currentVersionId, versions]);
  const browseIndex = browseVersionId
    ? versions.findIndex((v) => v.id === browseVersionId)
    : -1;
  const currentIndex = browsing && browseIndex !== -1 ? browseIndex : headIndex;
  const canUndo =
    !isGenerating && versions.length > 0 && currentIndex < versions.length - 1;
  const canRedo = !isGenerating && browsing && currentIndex > headIndex;
  const onUndo = () => {
    const target = versions[currentIndex + 1];
    if (target) setBrowseVersion(threadId, target.id);
  };
  const onRedo = () => {
    const newIndex = currentIndex - 1;
    // Stepping onto (or past) the head ends the browse — back to live.
    if (newIndex <= headIndex) setBrowseVersion(threadId, null);
    else setBrowseVersion(threadId, versions[newIndex]?.id ?? null);
  };

  // Revert: make the browsed version the head. The mutation invalidates the
  // record, versions, source, and builds caches (the server queues a rebuild),
  // so afterwards only the local browse state needs clearing.
  const { revertToVersion, isReverting } = useDashboardMutations();
  const onRevert = useCallback(async () => {
    if (!browseVersionId) return;
    try {
      await revertToVersion(dashboardId, browseVersionId);
      setBrowseVersion(threadId, null);
    } catch (error) {
      toast.error("Couldn't revert canvas", {
        description: error instanceof Error ? error.message : String(error),
      });
    }
  }, [
    browseVersionId,
    dashboardId,
    threadId,
    revertToVersion,
    setBrowseVersion,
  ]);

  // Head source, fetched only when there's no published artifact to render —
  // the pre-first-build client-render path. Keyed on the head version id so a
  // fresh publish refetches exactly once.
  const headVersionId = dashboard?.currentVersionId ?? null;
  const wantHeadSource = !!headVersionId && !!lifecycle && !publishedBuild;
  const { source: headSource, isLoading: headSourceLoading } = useCanvasSource({
    id: wantHeadSource ? dashboardId : undefined,
    versionId: headVersionId ?? undefined,
  });
  const headCode = headSource?.project.files[CANVAS_COMPONENT_PATH];

  // The browsed version's source (edit mode only).
  const { source: browseSource, isLoading: browseSourceLoading } =
    useCanvasSource({
      id: browsing ? dashboardId : undefined,
      versionId: browseVersionId ?? undefined,
    });
  const browseCode = browseSource?.project.files[CANVAS_COMPONENT_PATH];

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
  // injected here rather than resolved inside it.
  const onDataRequest = useCallback(
    (method: string, payload: unknown) => {
      if (!interactive) {
        try {
          // View mode enforces the published manifest's capabilities. They're
          // undefined while the manifest hasn't loaded — or when the canvas is
          // client-rendered from head source with no manifest at all — and the
          // assert allows that transient/manifest-less window instead of
          // hard-failing every read. The interactive path never asserts: the
          // author's own client keeps full data access while iterating.
          assertCanvasCapability(
            publishedBuild?.manifest?.capabilities,
            method,
            payload,
          );
        } catch (error) {
          return Promise.reject(error);
        }
      }
      return handleFreeformDataRequest(method, payload, queryClient);
    },
    [interactive, publishedBuild, queryClient],
  );

  const onError = useCallback(
    (message: string) => setRuntimeError(threadId, message),
    [threadId, setRuntimeError],
  );
  const onRendered = useCallback(() => {
    artifactLoadedRef.current = true;
    setRuntimeError(threadId, null);
  }, [threadId, setRuntimeError]);

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
  const hasSource = !!headVersionId;
  const hasContent = hasSource || !!pinnedArtifact;
  // `isGenerating` keys off the effective task (the optimistic bridge right after
  // submit, then the polled record) and short-circuits on a terminal run — so a
  // failed/cancelled run can't strand the canvas body on the spinner.
  // The empty-canvas landing: a centered composer with suggestions. Held back
  // until the record settles (so it doesn't flash over a canvas that has content)
  // and only when no run is in flight. After submit it floats into the panel.
  const showHero =
    interactive && !hasContent && !effectiveTaskId && !dashboardLoading;
  // The side panel only exists once there's a canvas or an active run.
  const showPanel = interactive && (hasContent || !!effectiveTaskId);
  // Build failures/progress surface in view mode too — the toolbar renders
  // there only while it has something to say.
  const hasBuildSignal =
    !!lifecycle &&
    lifecycle.builds.length > 0 &&
    (hasActiveCanvasBuild(lifecycle) ||
      latestFinishedCanvasBuild(lifecycle)?.buildStatus === "failed");
  const showToolbar = interactive || hasBuildSignal;

  return (
    <Flex height="100%" overflow="hidden" position="relative">
      {/* When the embedded chat isn't visible — panel minimized, or still shut
          mid-slide-in (waitingForHeroExit) — a paused tool-permission request
          would have nowhere to go, so surface it as a modal. When the panel is
          open, the chat handles it. */}
      {interactive && effectiveTaskId && (collapsed || waitingForHeroExit) && (
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
                  {isHomeCanvas && (
                    <Button
                      size="sm"
                      variant="default"
                      className="ml-1"
                      disabled={isGenerating || isResetting}
                      onClick={onResetToDefault}
                    >
                      <ArrowCounterClockwiseIcon size={14} />
                      {isResetting ? "Resetting…" : "Reset to default"}
                    </Button>
                  )}
                </>
              )}
            </Flex>
            <Flex align="center" gap="2">
              <CanvasBuildStatus
                dashboardId={dashboardId}
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
              {interactive && showPanel && collapsed && (
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
            browseSourceLoading ? (
              <ScrollArea className="h-full">
                <LoadingState />
              </ScrollArea>
            ) : browseCode ? (
              <Flex direction="column" className="h-full">
                <Flex
                  align="center"
                  justify="between"
                  className="shrink-0 border-b bg-accent-2 px-3 py-1.5"
                >
                  <Flex align="center" gap="1" className="text-accent-11">
                    <ClockCounterClockwiseIcon size={14} />
                    <Text size="1">
                      Viewing version — revert to make it live
                    </Text>
                  </Flex>
                  <Button
                    size="sm"
                    variant="primary"
                    disabled={isReverting}
                    onClick={() => void onRevert()}
                  >
                    {isReverting ? "Reverting…" : "Revert"}
                  </Button>
                </Flex>
                <Box className="min-h-0 flex-1">
                  {/* Reuses the canvas's warm frame with the browsed code. */}
                  <CanvasFramePlaceholder
                    dashboardId={dashboardId}
                    code={browseCode}
                    analytics={analytics}
                    onDataRequest={onDataRequest}
                    onError={onError}
                    onRendered={onRendered}
                    onNavigate={onNavigate}
                  />
                </Box>
              </Flex>
            ) : (
              <ScrollArea className="h-full">
                <Empty className="h-full border-0">
                  <EmptyHeader>
                    <EmptyMedia variant="icon">
                      <ClockCounterClockwiseIcon size={24} />
                    </EmptyMedia>
                    <EmptyTitle>Multi-file version</EmptyTitle>
                    <EmptyDescription>
                      This version has multiple source files, which render only
                      after a build — revert to make it live and rebuild it.
                    </EmptyDescription>
                  </EmptyHeader>
                  <EmptyContent>
                    <Flex align="center" gap="2">
                      <Button
                        variant="primary"
                        size="default"
                        disabled={isReverting}
                        onClick={() => void onRevert()}
                      >
                        {isReverting ? "Reverting…" : "Revert to this version"}
                      </Button>
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
                artifactUrl={pinnedArtifact.url}
                onDataRequest={onDataRequest}
                onError={onError}
                onReady={onArtifactReady}
                onRendered={onRendered}
                onNavigate={onNavigate}
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

      {showPanel && (
        <ResizableSidebar
          open={!collapsed && !waitingForHeroExit}
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
            onMinimize={() => setCollapsed(true)}
            dashboardId={dashboardId}
            channelId={channelId}
            channelName={channelName}
            name={dashboard?.name ?? "Canvas"}
            templateId={dashboard?.templateId}
            isEdit={hasSource}
            editorRef={editorRef}
            onStarted={setStartedTaskId}
          />
        </ResizableSidebar>
      )}

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
