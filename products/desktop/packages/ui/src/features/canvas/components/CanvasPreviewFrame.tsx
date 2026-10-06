import { publishedCanvasBuild } from "@posthog/core/canvas/canvasBuildSchemas";
import { Text } from "@posthog/quill";
import { BuiltCanvas } from "@posthog/ui/features/canvas/freeform/BuiltCanvas";
import { useCanvasBuilds } from "@posthog/ui/features/canvas/hooks/useCanvasBuilds";
import { useInView } from "@posthog/ui/primitives/hooks/useInView";
import { useCallback, useEffect, useState } from "react";

const LAYOUT_WIDTH = 1200;
const LAYOUT_HEIGHT = 820;

export function CanvasPreviewFrame({
  dashboardId,
  className,
}: {
  dashboardId: string;
  className?: string;
}) {
  const [ref, inView] = useInView<HTMLDivElement>({ rootMargin: "400px 0px" });
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

  const denyDataRequest = useCallback(
    () => Promise.reject(new Error("A canvas preview has no data access")),
    [],
  );

  return (
    <div ref={attach} className={className}>
      {inView && artifactUrl && width > 0 ? (
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
            capabilities={undefined}
            onDataRequest={denyDataRequest}
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
