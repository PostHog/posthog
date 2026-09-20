import { publishedCanvasBuild } from "@posthog/core/canvas/canvasBuildSchemas";
import { Text } from "@posthog/quill";
import { BuiltCanvas } from "@posthog/ui/features/canvas/freeform/BuiltCanvas";
import { handleFreeformDataRequest } from "@posthog/ui/features/canvas/freeform/freeformDataBridge";
import { useCanvasBuilds } from "@posthog/ui/features/canvas/hooks/useCanvasBuilds";
import { useInView } from "@posthog/ui/primitives/hooks/useInView";
import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";

/**
 * The width the artifact is laid out at before it is scaled down. A canvas is
 * authored for a pane, so rendering it at a card's width would reflow it into
 * something the card is not a picture of.
 */
const LAYOUT_WIDTH = 1200;
const LAYOUT_HEIGHT = 820;

/**
 * A canvas's published output, shrunk to fit a card.
 *
 * It is the real artifact on the real bridge, because a canvas that asks the
 * host for its data draws its own "could not load" panel when nothing answers,
 * and a card of that is worse than no card. Two things the bridge will not do
 * from here: ask the reader to approve a connector, or start an agent. A
 * preview is a picture, and a picture may not interrupt.
 *
 * Only mounts once the card is near the viewport: each one is a real render of
 * a real app, and a grid of them all booting at once is what the placeholder
 * this replaced was standing in for.
 */
export function CanvasPreviewFrame({
  dashboardId,
  className,
}: {
  dashboardId: string;
  className?: string;
}) {
  const [ref, inView] = useInView<HTMLDivElement>({ rootMargin: "400px 0px" });
  // `scale()` takes a number, so the factor is measured rather than written in
  // container units: dividing a length by a number yields a length, which the
  // property rejects, leaving the artifact at full size inside the card.
  const [box, setBox] = useState<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(0);
  const attach = useCallback(
    (node: HTMLDivElement | null) => {
      ref(node);
      setBox(node);
    },
    [ref],
  );
  useEffect(() => {
    if (!box) return;
    const observer = new ResizeObserver(([entry]) => {
      setWidth(entry.contentRect.width);
    });
    observer.observe(box);
    setWidth(box.clientWidth);
    return () => observer.disconnect();
  }, [box]);

  const { lifecycle, isLoading } = useCanvasBuilds(dashboardId, {
    enabled: inView,
  });
  const build = lifecycle ? publishedCanvasBuild(lifecycle) : undefined;
  const artifactUrl = build?.artifactUrl ?? null;
  const sourceVersionId = build?.sourceVersionId ?? undefined;

  const queryClient = useQueryClient();
  const onDataRequest = useCallback(
    (method: string, payload: unknown) => {
      if (method === "agentRequest") {
        return Promise.reject(
          new Error("A canvas preview cannot start an agent"),
        );
      }
      return handleFreeformDataRequest(method, payload, queryClient, {
        dashboardId,
        sourceVersionId,
        requestConnectorPermission: () => Promise.resolve(false),
      });
    },
    [dashboardId, queryClient, sourceVersionId],
  );

  return (
    <div ref={attach} className={className}>
      {artifactUrl && width > 0 ? (
        <div
          className="pointer-events-none origin-top-left"
          style={{
            width: LAYOUT_WIDTH,
            height: LAYOUT_HEIGHT,
            transform: `scale(${width / LAYOUT_WIDTH})`,
          }}
        >
          <BuiltCanvas
            artifactUrl={artifactUrl}
            capabilities={build?.manifest?.capabilities}
            onDataRequest={onDataRequest}
          />
        </div>
      ) : (
        <div className="flex h-full w-full items-center justify-center">
          <Text size="xs" variant="muted">
            {isLoading || !inView ? "" : "No preview yet"}
          </Text>
        </div>
      )}
    </div>
  );
}
