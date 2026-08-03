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
import { useCanvasBuilds } from "@posthog/ui/features/canvas/hooks/useCanvasBuilds";
import { Flex, Text, Tooltip } from "@radix-ui/themes";
import { useMutation, useQueryClient } from "@tanstack/react-query";

// Compact build indicator for the canvas toolbar: spinner while a queued
// publish builds, a quiet check once the live build is current, and the
// error diagnostics (in a tooltip) when the latest build failed — the canvas
// keeps rendering the last good build in that case.
export function CanvasBuildStatus({ dashboardId }: { dashboardId: string }) {
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
  if (!lifecycle || lifecycle.builds.length === 0) return null;

  if (hasActiveCanvasBuild(lifecycle)) {
    const queued = lifecycle.builds.find(
      (build) => build.buildStatus === "queued",
    );
    return (
      <Flex align="center" gap="1">
        <SpinnerGapIcon size={14} className="animate-spin text-gray-9" />
        <Text size="1" className="text-gray-10">
          Building
        </Text>
        {queued && (
          <Button
            size="icon"
            variant="default"
            aria-label="Cancel build"
            disabled={action.isPending}
            onClick={() =>
              action.mutate({
                id: dashboardId,
                buildId: queued.id,
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
    const errors = latest.diagnostics
      .filter((diagnostic) => diagnostic.severity === "error")
      .slice(0, 3)
      .map((diagnostic) => diagnostic.message)
      .join("\n");
    return (
      <Tooltip
        content={`Latest build failed — the previous version stays live.\n${errors}`}
      >
        <Flex align="center" gap="1" data-testid="canvas-build-failed">
          <WarningCircleIcon size={14} className="text-red-9" />
          <Text size="1" className="text-red-10">
            Build failed
          </Text>
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
      </Tooltip>
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
