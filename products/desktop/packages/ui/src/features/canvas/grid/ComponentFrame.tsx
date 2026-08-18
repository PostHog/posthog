import type { GridPlacement } from "@posthog/core/canvas/gridLayoutSchemas";
import { Spinner, Text } from "@posthog/quill";
import type { CanvasCapabilities } from "@posthog/shared";
import { useCanvasBuilds } from "@posthog/ui/features/canvas/hooks/useCanvasBuilds";
import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo } from "react";
import { BuiltCanvas } from "../freeform/BuiltCanvas";
import { handleFreeformDataRequest } from "../freeform/freeformDataBridge";
import { usePinnedArtifact } from "../freeform/usePinnedArtifact";

/**
 * One live placement's widget: the component canvas's published build artifact
 * in its own sandboxed frame. Data requests, state, and capabilities are all
 * scoped to the COMPONENT canvas — each widget is held to the contract its own
 * build shipped with, independent of its neighbors.
 */
export function ComponentFrame({ placement }: { placement: GridPlacement }) {
  const componentId = placement.component ?? "";
  const queryClient = useQueryClient();
  const { lifecycle, dataUpdatedAt } = useCanvasBuilds(
    componentId || undefined,
  );
  const publishedBuild = useMemo(
    () =>
      lifecycle?.builds.find(
        (build) => build.id === lifecycle.publishedBuildId,
      ) ?? null,
    [lifecycle],
  );
  const { artifact, refreshKey, onReady } = usePinnedArtifact({
    dashboardId: componentId,
    publishedBuild,
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

  const capabilities = publishedBuild?.manifest
    ? ((publishedBuild.manifest as { capabilities?: CanvasCapabilities })
        .capabilities ?? undefined)
    : undefined;
  const config = useMemo(
    () => (placement.config as Record<string, unknown> | null) ?? undefined,
    [placement.config],
  );

  if (!artifact) {
    // No artifact and no build coming: an endless spinner here hides a broken
    // widget — the checklist a fresh home seeds hits this when its build fails.
    const newestBuild = lifecycle?.builds[0];
    const buildDead =
      lifecycle &&
      !publishedBuild &&
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
      onReady={onReady}
      onRendered={onReady}
    />
  );
}
