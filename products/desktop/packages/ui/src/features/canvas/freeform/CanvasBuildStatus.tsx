import {
  ArrowClockwiseIcon,
  CheckCircleIcon,
  PushPinIcon,
  SpinnerGapIcon,
  WarningCircleIcon,
  XIcon,
} from "@phosphor-icons/react";
import {
  type CanvasBuildLifecycle,
  currentHeadBuildFailure,
  latestFinishedCanvasBuild,
} from "@posthog/core/canvas/canvasBuildSchemas";
import { useHostTRPC } from "@posthog/host-router/react";
import {
  Button,
  Text,
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@posthog/quill";
import type { CanvasDiagnostic } from "@posthog/shared";
import { toast } from "@posthog/ui/primitives/toast";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

// How often the queued/building elapsed-time label refreshes. Coarse on
// purpose — it's a progress hint, not a stopwatch.
const ELAPSED_TICK_MS = 5_000;

function formatElapsed(ms: number): string {
  const seconds = Math.max(0, Math.floor(ms / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ${seconds % 60}s`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

// The top error diagnostics, one per line, for tooltips and fix prompts.
function topErrors(diagnostics: CanvasDiagnostic[]): string[] {
  return diagnostics
    .filter((diagnostic) => diagnostic.severity === "error")
    .slice(0, 3)
    .map((diagnostic) =>
      diagnostic.path
        ? `${diagnostic.path}${diagnostic.line ? `:${diagnostic.line}` : ""} — ${diagnostic.message}`
        : diagnostic.message,
    );
}

// Compact build indicator for the canvas toolbar (both view and edit mode):
// spinner + elapsed time while a queued publish builds, a quiet check once the
// live build is current, and the error diagnostics (in a tooltip) when the
// latest build failed — the canvas keeps rendering the last good build in that
// case. `onAskAgentToFix` (edit mode) prefills the edit composer with the top
// diagnostics, mirroring the runtime-error self-repair affordance.
export function CanvasBuildStatus({
  dashboardId,
  lifecycle,
  onAskAgentToFix,
}: {
  dashboardId: string;
  lifecycle: CanvasBuildLifecycle | undefined;
  onAskAgentToFix?: (prompt: string) => void;
}) {
  const trpc = useHostTRPC();
  const queryClient = useQueryClient();
  const action = useMutation(
    trpc.dashboards.actOnBuild.mutationOptions({
      onSuccess: () =>
        queryClient.invalidateQueries({
          queryKey: trpc.dashboards.builds.queryKey({ id: dashboardId }),
        }),
      onError: (error) =>
        toast.error("Couldn't update canvas build", {
          description: error instanceof Error ? error.message : String(error),
        }),
    }),
  );
  const active = lifecycle?.builds.find(
    (build) =>
      build.buildStatus === "queued" || build.buildStatus === "building",
  );
  const activeId = active?.id;

  // Elapsed-time ticker for the active build: the interval only forces a
  // re-render, the label is derived from the clock during render. Keyed on the
  // build id so a new build restarts the ticker; idle when no build is active.
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!activeId) return;
    const timer = setInterval(
      () => setTick((tick) => tick + 1),
      ELAPSED_TICK_MS,
    );
    return () => clearInterval(timer);
  }, [activeId]);

  if (!lifecycle || lifecycle.builds.length === 0) return null;

  if (active) {
    const elapsed = formatElapsed(Date.now() - Date.parse(active.createdAt));
    return (
      <div
        className="flex items-center gap-1"
        data-testid="canvas-build-active"
      >
        <SpinnerGapIcon size={14} className="animate-spin text-gray-9" />
        <Text size="xs" variant="muted">
          {active.buildStatus === "queued" ? "Queued" : "Building"} · {elapsed}
        </Text>
        {active.buildStatus === "queued" && (
          <Button
            size="icon"
            variant="default"
            aria-label="Cancel build"
            disabled={action.isPending}
            onClick={() =>
              action.mutate({
                id: dashboardId,
                buildId: active.id,
                action: "cancel",
              })
            }
          >
            <XIcon size={14} />
          </Button>
        )}
      </div>
    );
  }

  // Surface a failed build of the CURRENT head even when an older (pinned /
  // published) finished build appears first in the list — array position must
  // not hide a failed newest publish.
  const failedHead = currentHeadBuildFailure(lifecycle);
  const latest = failedHead ?? latestFinishedCanvasBuild(lifecycle);
  if (!latest) return null;

  if (latest.buildStatus === "failed") {
    const errors = topErrors(latest.diagnostics);
    return (
      <div
        className="flex items-center gap-1"
        data-testid="canvas-build-failed"
      >
        <TooltipProvider delay={0}>
          <Tooltip>
            <TooltipTrigger
              render={
                <div className="flex items-center gap-1">
                  <WarningCircleIcon size={14} className="text-red-9" />
                  <Text size="xs" className="text-red-10">
                    Build failed
                  </Text>
                </div>
              }
            />
            <TooltipContent>
              <span className="whitespace-pre-wrap">
                {[
                  "Latest build failed. The previous version stays live.",
                  ...errors,
                ].join("\n")}
              </span>
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
        {onAskAgentToFix && (
          <Button
            size="sm"
            variant="outline"
            onClick={() =>
              onAskAgentToFix(
                [
                  "The canvas build failed with these errors:",
                  ...errors.map((error) => `- ${error}`),
                  "Fix the canvas source so the build succeeds.",
                ].join("\n"),
              )
            }
          >
            Ask agent to fix
          </Button>
        )}
        <Button
          size="icon"
          variant="default"
          aria-label="Retry build"
          disabled={action.isPending}
          onClick={() =>
            action.mutate({
              id: dashboardId,
              buildId: latest.id,
              action: "retry",
            })
          }
        >
          <ArrowClockwiseIcon size={14} />
        </Button>
      </div>
    );
  }

  if (lifecycle.publishedBuildId === latest.id) {
    return (
      <TooltipProvider delay={0}>
        <Tooltip>
          <TooltipTrigger
            render={
              <div
                className="flex items-center gap-1"
                data-testid="canvas-build-ready"
              >
                <CheckCircleIcon size={14} className="text-green-9" />
                <Button
                  size="icon"
                  variant="default"
                  aria-label={latest.pinned ? "Unpin build" : "Pin build"}
                  disabled={action.isPending}
                  onClick={() =>
                    action.mutate({
                      id: dashboardId,
                      buildId: latest.id,
                      action: latest.pinned ? "unpin" : "pin",
                    })
                  }
                >
                  <PushPinIcon
                    size={14}
                    weight={latest.pinned ? "fill" : "regular"}
                  />
                </Button>
              </div>
            }
          />
          <TooltipContent>The live build is up to date.</TooltipContent>
        </Tooltip>
      </TooltipProvider>
    );
  }

  const published = lifecycle.builds.find(
    (build) => build.id === lifecycle.publishedBuildId,
  );
  if (latest.buildStatus === "ready" && published?.pinned) {
    return (
      <TooltipProvider delay={0}>
        <Tooltip>
          <TooltipTrigger
            render={
              <div
                className="flex items-center gap-1"
                data-testid="canvas-build-pinned-older"
              >
                <Text size="xs">Newer build available</Text>
                <Button
                  size="icon"
                  variant="default"
                  aria-label="Unpin build"
                  disabled={action.isPending}
                  onClick={() =>
                    action.mutate({
                      id: dashboardId,
                      buildId: published.id,
                      action: "unpin",
                    })
                  }
                >
                  <PushPinIcon size={14} weight="fill" />
                </Button>
              </div>
            }
          />
          <TooltipContent>
            A newer build is ready, but an older build is pinned live.
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    );
  }

  return null;
}
