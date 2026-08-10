import LogosLandscape from "@posthog/ui/primitives/Logo";
import { createPortal } from "react-dom";
import { useMissionControlStore } from "./missionControlStore";

// Unanimated on purpose: at Mission Control's thumbnail scale a transition
// reads as a rendering glitch.
export function MissionControlOverlay() {
  const active = useMissionControlStore((state) => state.active);

  if (!active) return null;

  // Portalling to document.body would land outside the Radix <Theme> subtree
  // and render a light panel in dark mode.
  const container =
    document.getElementById("portal-container") ?? document.body;

  return createPortal(
    <div
      aria-hidden="true"
      data-testid="mission-control-overlay"
      className="pointer-events-none fixed inset-0 z-[300] flex flex-col items-center justify-center gap-[2.5vh] bg-(--gray-1)/75 backdrop-blur-md"
    >
      {/* The logo-only variant reserves room for the wordmark, so crop to the
          logomark's own 52:28 box. */}
      <div
        className="w-[min(18vw,160px)] overflow-hidden [&>svg]:h-auto [&>svg]:w-full"
        style={{ aspectRatio: "52 / 28" }}
      >
        <LogosLandscape wordmark={false} />
      </div>
      <p className="font-semibold text-(--gray-12) text-[clamp(16px,2.2vw,28px)] leading-none tracking-tight">
        PostHog Desktop
      </p>
    </div>,
    container,
  );
}
