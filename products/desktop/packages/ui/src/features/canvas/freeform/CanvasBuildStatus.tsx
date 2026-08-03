import {
  ArrowClockwiseIcon,
  CheckCircleIcon,
  PushPinIcon,
  SpinnerGapIcon,
  WarningCircleIcon,
  XIcon,
} from "@phosphor-icons/react";
import {
  hasActiveCanvasBuild,
  latestFinishedCanvasBuild,
} from "@posthog/core/canvas/canvasBuildSchemas";
import { useHostTRPC } from "@posthog/host-router/react";
import { Button } from "@posthog/quill";
import type { CanvasDiagnostic } from "@posthog/shared";
import { useCanvasBuilds } from "@posthog/ui/features/canvas/hooks/useCanvasBuilds";
import { Flex, Text, Tooltip } from "@radix-ui/themes";
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
  onAskAgentToFix,
}: {
  dashboardId: string;
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
    }),
  );
  const { lifecycle } = useCanvasBuilds(dashboardId);

  const active = lifecycle?.builds.find(
    (build) =>
      build.buildStatus === "queued" || build.buildStatus === "building",
  );
  const activeId = active?.id;

  // Elapsed-time ticker for the active build. Keyed on the build id so a new
  // build restarts the clock; idle when no build is active.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!activeId) return;
    setNow(Date.now());
    const timer = setInterval(() => setNow(Date.now()), ELAPSED_TICK_MS);
    return () => clearInterval(timer);
  }, [activeId]);

  if (!lifecycle || lifecycle.builds.length === 0) return null;

  if (active && hasActiveCanvasBuild(lifecycle)) {
    const elapsed = formatElapsed(now - Date.parse(active.createdAt));
    return (
      <Flex align="center" gap="1" data-testid="canvas-build-active">
        <SpinnerGapIcon size={14} className="animate-spin text-gray-9" />
        <Text size="1" className="text-gray-10">
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
      </Flex>
    );
  }

  const latest = latestFinishedCanvasBuild(lifecycle);
  if (!latest) return null;

  if (latest.buildStatus === "failed") {
    const errors = topErrors(latest.diagnostics);
    return (
      <Flex align="center" gap="1" data-testid="canvas-build-failed">
        <Tooltip
          content={[
            "Latest build failed — the previous version stays live.",
            ...errors,
          ].join("\n")}
        >
          <Flex align="center" gap="1">
            <WarningCircleIcon size={14} className="text-red-9" />
            <Text size="1" className="text-red-10">
              Build failed
            </Text>
          </Flex>
        </Tooltip>
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
      </Flex>
    );
  }

  if (lifecycle.publishedBuildId === latest.id) {
    return (
      <Tooltip content="The live build is up to date.">
        <Flex align="center" gap="1" data-testid="canvas-build-ready">
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
        </Flex>
      </Tooltip>
    );
  }

  return null;
}
