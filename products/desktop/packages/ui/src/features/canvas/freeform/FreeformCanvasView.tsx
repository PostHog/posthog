import {
  ArrowCounterClockwiseIcon,
  ArrowUUpLeftIcon,
  ArrowUUpRightIcon,
  ShapesIcon,
  SidebarSimpleIcon,
  SpinnerGapIcon,
  WarningIcon,
} from "@phosphor-icons/react";
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
import {
  isCanvasGenerating,
  isCanvasGenerationRunning,
} from "@posthog/ui/features/canvas/freeform/canvasGenerationStatus";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useCanvasChatPanelStore } from "@posthog/ui/features/canvas/stores/canvasChatPanelStore";
import {
  useFreeformChatStore,
  useFreeformThread,
} from "@posthog/ui/features/canvas/stores/freeformChatStore";
import type { EditorHandle } from "@posthog/ui/features/message-editor/types";
import { useSessionForTask } from "@posthog/ui/features/sessions/useSession";
import { taskDetailQuery } from "@posthog/ui/features/tasks/queries";
import { ResizableSidebar } from "@posthog/ui/primitives/ResizableSidebar";
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
import { useCallback, useMemo, useRef, useState } from "react";
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

// A freeform (React-in-iframe) canvas: the sandboxed app, with version controls
// and an edit composer (edit mode only). Generation runs as a dedicated task —
// when one is in flight the screen shows a "Generating… View task" state, like
// CONTEXT.md. The published result is adopted into the canvas record and synced
// into the working copy by WebsiteDashboard.
export function FreeformCanvasView({
  threadId,
  interactive,
}: {
  threadId: string;
  interactive: boolean;
}) {
  const dashboardId = dashboardIdOf(threadId);
  const { code, versions, currentVersionId, runtimeError } =
    useFreeformThread(threadId);
  const undo = useFreeformChatStore((s) => s.undo);
  const redo = useFreeformChatStore((s) => s.redo);
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

  // The generation-task association lives in the canvas record's meta. Poll it
  // while a task is running so the published code + the cleared association show
  // up without a manual refresh (WebsiteDashboard re-syncs the working copy).
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
  // Whether the run's session is still alive. Drives record polling so a freshly
  // published canvas gets picked up. A local ACP session stays "connected" after
  // its generation prompt finishes, so this keeps syncing until it disconnects.
  // Uses the shared, tested helper, which also stops once the run record is
  // terminal so a stale/stuck session can't keep us polling forever.
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

  // Poll the record while the session is alive so a just-published canvas
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

  const idx = versions.findIndex((v) => v.id === currentVersionId);
  const canUndo = idx > 0;
  const canRedo = idx !== -1 && idx < versions.length - 1;

  // The data bridge is a pure function; the QueryClient (its read cache) is
  // injected here rather than resolved inside it.
  const queryClient = useQueryClient();
  const onDataRequest = useCallback(
    (method: string, payload: unknown) =>
      handleFreeformDataRequest(method, payload, queryClient),
    [queryClient],
  );

  const onError = useCallback(
    (message: string) => setRuntimeError(threadId, message),
    [threadId, setRuntimeError],
  );
  const onRendered = useCallback(
    () => setRuntimeError(threadId, null),
    [threadId, setRuntimeError],
  );

  // Routes the canvas's allowlisted nav intents within this channel.
  const onNavigate = useCanvasNavigation(channelId);

  // The edit composer's editor handle, so self-repair can prefill it.
  const editorRef = useRef<EditorHandle>(null);
  const askAgentToFix = () => {
    if (!runtimeError) return;
    // Reveal the panel composer and prefill it. The panel stays mounted while
    // collapsed, so the editor handle is available even from a minimized panel.
    setCollapsed(false);
    editorRef.current?.setContent(
      `The app threw a runtime error: "${runtimeError}". Fix it and rewrite the whole file.`,
    );
    editorRef.current?.focus();
  };

  // The working copy (`code`) is only seeded from the record by WebsiteDashboard
  // once `dashboards.get` lands, so fall back to the record's stored code to
  // bridge the gap before that seed runs — the seeded value is identical, so a
  // canvas with content renders right away instead of flashing the empty state.
  // Deriving from the record rather than waiting on the seed also means a seed
  // that never runs can't strand the canvas on a spinner.
  const renderCode = code || dashboard?.code || "";
  const showCanvas = !!renderCode;
  // `isGenerating` keys off the effective task (the optimistic bridge right after
  // submit, then the polled record) and short-circuits on a terminal run — so a
  // failed/cancelled run can't strand the canvas body on the spinner.
  const showGeneratingState = !renderCode && isGenerating;
  // While the record is still being fetched we don't yet know whether the canvas
  // has content, so show a spinner instead of the empty state / hero. Bounded by
  // the query, so it resolves once the fetch settles.
  const showLoadingState = !renderCode && !isGenerating && dashboardLoading;
  // The empty-canvas landing: a centered composer with suggestions. Held back
  // until the record settles (so it doesn't flash over a canvas that has content)
  // and only when no run is in flight. After submit it floats into the panel.
  const showHero =
    interactive && !renderCode && !effectiveTaskId && !dashboardLoading;
  // The side panel only exists once there's a canvas or an active run.
  const showPanel = interactive && (showCanvas || !!effectiveTaskId);

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
        {interactive && (
          <Flex
            align="center"
            justify="between"
            className="h-10 shrink-0 items-center border-b bg-chrome px-3"
          >
            <Flex align="center" gap="1">
              <Button
                size="icon"
                variant="default"
                aria-label="Undo"
                disabled={!canUndo || isGenerating}
                onClick={() => undo(threadId)}
              >
                <ArrowUUpLeftIcon size={16} />
              </Button>
              <Button
                size="icon"
                variant="default"
                aria-label="Redo"
                disabled={!canRedo || isGenerating}
                onClick={() => redo(threadId)}
              >
                <ArrowUUpRightIcon size={16} />
              </Button>
              {versions.length > 0 && (
                <Text size="1" className="ml-1 text-gray-9">
                  v{idx + 1}/{versions.length}
                </Text>
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
            </Flex>
            <Flex align="center" gap="2">
              {isGenerating && effectiveTaskId ? (
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
                    <Button size="sm" variant="outline" onClick={askAgentToFix}>
                      Ask agent to fix
                    </Button>
                  </>
                )
              )}
              {showPanel && collapsed && (
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
          {showCanvas ? (
            // The iframe lives in the persistent warm-frame pool (CanvasFrameHost);
            // this placeholder just reserves the viewport box and owns scroll via
            // the host's overlay, so the canvas survives navigation without a reload.
            <Box className="h-full w-full">
              <CanvasFramePlaceholder
                dashboardId={dashboardId}
                code={renderCode}
                analytics={analytics}
                onDataRequest={onDataRequest}
                onError={onError}
                onRendered={onRendered}
                onNavigate={onNavigate}
              />
            </Box>
          ) : (
            <ScrollArea className="h-full">
              {showGeneratingState ? (
                <GeneratingState
                  channelId={channelId}
                  taskId={effectiveTaskId ?? ""}
                />
              ) : showLoadingState ? (
                <LoadingState />
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
            currentCode={renderCode || undefined}
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
// content doesn't flash the empty state before its code syncs into the thread.
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
