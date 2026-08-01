import { ErrorBoundary } from "@posthog/ui/shell/ErrorBoundary";
import type { CSSProperties } from "react";
import { useCanvasFrameStore } from "./canvasFrameStore";
import { FreeformCanvas } from "./FreeformCanvas";

// Persistent warm-iframe pool, mounted once by WebsiteLayout so it survives every
// in-space navigation. Each pool slot is a long-lived FreeformCanvas (keyed by slot
// index, never re-parented) overlaid onto the active canvas's placeholder rect. The
// active slot is visible + interactive; warm-but-hidden slots keep their iframe (and
// its rendered DOM, scroll, fetched data) alive for an instant return.
export function CanvasFrameHost() {
  const slots = useCanvasFrameStore((s) => s.slots);
  const activeDashboardId = useCanvasFrameStore((s) => s.activeDashboardId);
  const frameKeys = useCanvasFrameStore((s) => s.frameKeys);

  return (
    // Fixed, viewport-filling, click-through layer. Children are positioned in
    // viewport coordinates (the placeholder's getBoundingClientRect). Kept below
    // the header (z 100) and app modals; only the active slot is visible/interactive.
    <div
      style={{
        position: "fixed",
        inset: 0,
        pointerEvents: "none",
        zIndex: 5,
      }}
    >
      {slots.map((slot, slotId) => {
        if (!slot) return null;
        const active = slot.dashboardId === activeDashboardId && !!slot.rect;
        const rect = slot.rect;
        const style: CSSProperties = {
          position: "absolute",
          top: rect?.top ?? 0,
          left: rect?.left ?? 0,
          width: rect?.width ?? 0,
          height: rect?.height ?? 0,
          // The iframe fills this slot exactly and scrolls its own content
          // internally, so the wrapper only clips — it never scrolls.
          overflow: "hidden",
          visibility: active ? "visible" : "hidden",
          pointerEvents: active ? "auto" : "none",
        };
        // Keyed by the physical frame's identity (its slot index), NOT dashboardId:
        // reassigning a slot to a new canvas must reuse the same iframe (init
        // code-swap), not remount it — remounting re-parents the iframe = reload.
        // The remount generation (bumped only by an explicit user Refresh) is
        // folded in so that action — and only that action — recreates the iframe.
        const frameKey = `slot-${slotId}-${frameKeys[slotId] ?? 0}`;
        return (
          <div key={frameKey} style={style}>
            <ErrorBoundary name="freeform-canvas" resetKey={slot.dashboardId}>
              <FreeformCanvas
                code={slot.inputs.code}
                mode="edit"
                analytics={slot.inputs.analytics}
                onDataRequest={slot.inputs.onDataRequest}
                onError={slot.inputs.onError}
                onRendered={slot.inputs.onRendered}
                onNavigate={slot.inputs.onNavigate}
              />
            </ErrorBoundary>
          </div>
        );
      })}
    </div>
  );
}
