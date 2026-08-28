import { placementComponentBuild } from "@posthog/core/canvas/canvasBuildSchemas";
import {
  type GridPlacement,
  pinnedComponentVersion,
} from "@posthog/core/canvas/gridLayoutSchemas";
import { Button, Spinner, Text } from "@posthog/quill";
import type { CanvasCapabilities } from "@posthog/shared";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { useCanvasBuilds } from "@posthog/ui/features/canvas/hooks/useCanvasBuilds";
import { track } from "@posthog/ui/shell/analytics";
import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo, useRef } from "react";
import { BuiltCanvas } from "../freeform/BuiltCanvas";
import { canvasRuntimeErrorAnalytics } from "../freeform/canvasRuntimeError";
import { handleFreeformDataRequest } from "../freeform/freeformDataBridge";
import { usePinnedArtifact } from "../freeform/usePinnedArtifact";

/**
 * One live placement's widget: the component canvas's built artifact in its own
 * sandboxed frame. Data requests, state, and capabilities are all scoped to the
 * COMPONENT canvas — each widget is held to the contract its own build shipped
 * with, independent of its neighbors.
 */
export function ComponentFrame({ placement }: { placement: GridPlacement }) {
  const componentId = placement.component ?? "";
  const queryClient = useQueryClient();
  // A pinned placement asks for one specific source version: request it by id
  // so the endpoint includes its build even when newer builds pushed it out of
  // the lifecycle window.
  const pinnedVersion = pinnedComponentVersion(placement);
  const { lifecycle, isError, dataUpdatedAt, refetch } = useCanvasBuilds(
    componentId || undefined,
    { versionId: pinnedVersion ?? undefined },
  );
  const renderedBuild = useMemo(
    () =>
      lifecycle ? placementComponentBuild(lifecycle, pinnedVersion) : null,
    [lifecycle, pinnedVersion],
  );
  const { artifact, refreshKey, onReady } = usePinnedArtifact({
    dashboardId: componentId,
    publishedBuild: renderedBuild,
    lifecycle,
    mintedAt: dataUpdatedAt,
    suspended: false,
  });

  const onDataRequest = useCallback(
    (method: string, payload: unknown) =>
      handleFreeformDataRequest(method, payload, queryClient, {
        dashboardId: componentId,
      }),
    [queryClient, componentId],
  );

  const capabilities = renderedBuild?.manifest
    ? ((renderedBuild.manifest as { capabilities?: CanvasCapabilities })
        .capabilities ?? undefined)
    : undefined;
  const config = useMemo(
    () => (placement.config as Record<string, unknown> | null) ?? undefined,
    [placement.config],
  );
  const lastRuntimeErrorRef = useRef<string | null>(null);
  const onError = useCallback(
    (message: string) => {
      if (message === lastRuntimeErrorRef.current) return;
      lastRuntimeErrorRef.current = message;
      track(ANALYTICS_EVENTS.CANVAS_RUNTIME_ERROR, {
        dashboard_id: componentId,
        build_id: artifact?.buildId,
        ...canvasRuntimeErrorAnalytics(message),
      });
    },
    [artifact?.buildId, componentId],
  );
  const onArtifactReady = useCallback(() => {
    lastRuntimeErrorRef.current = null;
    onReady();
  }, [onReady]);

  if (!artifact) {
    // The lifecycle loaded and the pinned version has no artifact in it: build
    // retention can sweep one, and rendering the component's latest build
    // instead would silently swap the widget. Refetching cannot bring it back,
    // so this state offers no retry.
    if (pinnedVersion && lifecycle && !renderedBuild) {
      return (
        <div className="flex h-full w-full flex-col items-center justify-center gap-1 overflow-hidden p-3 text-center">
          <Text size="sm">This widget's pinned version isn't available.</Text>
          <Text size="xs" variant="muted">
            Point the widget at the component's latest version to bring it back.
          </Text>
        </div>
      );
    }
    // No artifact and no build coming: an endless spinner here hides a broken
    // widget — the checklist a fresh home seeds hits this when its build fails.
    const newestBuild = lifecycle?.builds[0];
    const buildDead =
      lifecycle &&
      !renderedBuild &&
      (!newestBuild || newestBuild.buildStatus === "failed");
    if (buildDead) {
      const failure = newestBuild?.diagnostics.find(
        (entry) => entry.severity === "error",
      )?.message;
      return (
        <div className="flex h-full w-full flex-col items-center justify-center gap-1 overflow-hidden p-3 text-center">
          <Text size="sm">This widget failed to build.</Text>
          {failure ? (
            <Text size="xs" variant="muted" className="line-clamp-3">
              {failure}
            </Text>
          ) : null}
          <Text size="xs" variant="muted">
            Open the component canvas to fix and republish.
          </Text>
        </div>
      );
    }
    // The build lifecycle fetch failed for good (retries exhausted) and there's
    // no data to fall back on — a permanent failure like a deleted component
    // canvas. Without this the tile spins forever with no way out.
    if (isError && !lifecycle) {
      return (
        <div className="flex h-full w-full flex-col items-center justify-center gap-1 overflow-hidden p-3 text-center">
          <Text size="sm">This widget couldn't load.</Text>
          <Text size="xs" variant="muted">
            It may have been removed, or the connection dropped.
          </Text>
          <Button variant="outline" size="sm" onClick={refetch}>
            Retry
          </Button>
        </div>
      );
    }
    return (
      <div className="flex h-full w-full items-center justify-center">
        <Spinner />
      </div>
    );
  }
  return (
    <BuiltCanvas
      key={`${artifact.buildId}:${refreshKey}`}
      artifactUrl={artifact.url}
      capabilities={capabilities}
      config={config}
      onDataRequest={onDataRequest}
      onError={onError}
      onReady={onArtifactReady}
      onRendered={onArtifactReady}
    />
  );
}
