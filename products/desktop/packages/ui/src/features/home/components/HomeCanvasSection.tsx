import { ArrowRightIcon } from "@phosphor-icons/react";
import { publishedCanvasBuild } from "@posthog/core/canvas/canvasBuildSchemas";
import type { DashboardRecord } from "@posthog/core/canvas/dashboardSchemas";
import { Button, Card } from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { BuiltCanvas } from "@posthog/ui/features/canvas/freeform/BuiltCanvas";
import { handleFreeformDataRequest } from "@posthog/ui/features/canvas/freeform/freeformDataBridge";
import { useCanvasBuilds } from "@posthog/ui/features/canvas/hooks/useCanvasBuilds";
import { HomeSection } from "@posthog/ui/features/home/components/HomeSection";
import { navigateToChannelDashboard } from "@posthog/ui/router/navigationBridge";
import { track } from "@posthog/ui/shell/analytics";
import { useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

/**
 * How tall a stacked canvas gets. Canvases are authored to fill a viewport and
 * the runtime reports no content height, so Home gives each one a band and
 * leaves the whole canvas one click away.
 */
const CANVAS_HEIGHT_PX = 460;

/**
 * One canvas in Home's stack: the published build, live, in the same sandboxed
 * frame the canvas's own page uses — so the section is the real canvas rather
 * than a picture of it. Unpublished canvases say so instead of showing a blank
 * band.
 */
export function HomeCanvasSection({ canvas }: { canvas: DashboardRecord }) {
  const queryClient = useQueryClient();
  const { lifecycle } = useCanvasBuilds(canvas.id);
  const build = lifecycle ? publishedCanvasBuild(lifecycle) : null;

  // The bridge is a pure function; its read cache is the app's QueryClient, so
  // a canvas open in Home and the same canvas open on its own page share reads.
  const onDataRequest = useCallback(
    (method: string, payload: unknown) =>
      handleFreeformDataRequest(method, payload, queryClient),
    [queryClient],
  );

  const open = () => {
    track(ANALYTICS_EVENTS.HOME_ACTION, { action_type: "open_canvas" });
    navigateToChannelDashboard(canvas.channelId, canvas.id);
  };

  return (
    <HomeSection
      title={canvas.name}
      action={
        <Button variant="outline" onClick={open}>
          Open
          <ArrowRightIcon size={14} />
        </Button>
      }
    >
      {build?.artifactUrl ? (
        <div
          className="overflow-hidden rounded-md border border-border"
          style={{ height: CANVAS_HEIGHT_PX }}
        >
          <BuiltCanvas
            key={build.id}
            artifactUrl={build.artifactUrl}
            capabilities={build.manifest?.capabilities}
            onDataRequest={onDataRequest}
          />
        </div>
      ) : (
        <Card className="flex flex-row items-center justify-between gap-3 p-3">
          <span className="text-muted-foreground text-sm">
            This canvas has no published build yet.
          </span>
          <Button variant="outline" onClick={open}>
            Open canvas
          </Button>
        </Card>
      )}
    </HomeSection>
  );
}
