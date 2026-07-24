import type {
  CanvasAnalyticsConfig,
  CanvasNavIntent,
} from "@posthog/core/canvas/freeformSchemas";
import { useLayoutEffect, useMemo, useRef } from "react";
import { useCanvasFrameStore } from "./canvasFrameStore";

// Stands in for the canvas inside the route tree. It renders nothing visible —
// just an empty box that reserves the canvas viewport — and hands the actual
// rendering to the persistent warm-frame pool (CanvasFrameHost): it registers this
// canvas's inputs, activates it on mount (deactivates on unmount, keeping the frame
// warm), and reports its on-screen rect so the host can overlay the warm iframe.
export function CanvasFramePlaceholder({
  dashboardId,
  code,
  analytics,
  onDataRequest,
  onError,
  onRendered,
  onNavigate,
}: {
  dashboardId: string;
  code: string;
  analytics?: CanvasAnalyticsConfig;
  onDataRequest: (method: string, payload: unknown) => Promise<unknown>;
  onError?: (message: string, stack?: string) => void;
  onRendered?: () => void;
  onNavigate?: (intent: CanvasNavIntent) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);

  const register = useCanvasFrameStore((s) => s.register);
  const setRect = useCanvasFrameStore((s) => s.setRect);
  const activate = useCanvasFrameStore((s) => s.activate);
  const deactivate = useCanvasFrameStore((s) => s.deactivate);

  const inputs = useMemo(
    () => ({
      code,
      analytics,
      onDataRequest,
      onError,
      onRendered,
      onNavigate,
    }),
    [code, analytics, onDataRequest, onError, onRendered, onNavigate],
  );

  // Layout effect (not passive) and declared first, so the slot exists before the
  // rect-measure effect below runs its initial synchronous measure. Otherwise the
  // slot is created too late (setRect no-ops with no slot) and the frame only
  // becomes visible once a later scroll/resize re-measures — which never happens
  // on a settled layout, so a canvas opened while the app has been running a while
  // (e.g. via a deep link) stays hidden until a hard refresh.
  useLayoutEffect(() => {
    register(dashboardId, inputs);
  }, [dashboardId, inputs, register]);

  useLayoutEffect(() => {
    activate(dashboardId);
    return () => deactivate(dashboardId);
  }, [dashboardId, activate, deactivate]);

  // Track the placeholder's viewport box. A capture-phase scroll listener catches
  // ancestor scrolling (not just this element), so the overlaid frame stays glued.
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => {
      const r = el.getBoundingClientRect();
      setRect(dashboardId, {
        top: r.top,
        left: r.left,
        width: r.width,
        height: r.height,
      });
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    window.addEventListener("scroll", measure, true);
    window.addEventListener("resize", measure);
    return () => {
      ro.disconnect();
      window.removeEventListener("scroll", measure, true);
      window.removeEventListener("resize", measure);
    };
  }, [dashboardId, setRect]);

  return <div ref={ref} className="h-full w-full" />;
}
