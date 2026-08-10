import LogosLandscape from "@posthog/ui/primitives/Logo";
import { createPortal } from "react-dom";
import { useMissionControlStore } from "./missionControlStore";

/**
 * Brands the window while macOS Mission Control is open, so it can be picked out
 * of a grid of near-identical dark windows.
 *
 * Unanimated on purpose: Mission Control shrinks the window to roughly a sixth of
 * its size, where a transition reads as a rendering glitch.
 */
export function MissionControlOverlay() {
  const active = useMissionControlStore((state) => state.active);

  if (!active) return null;

  // ThemeWrapper exposes this container inside the Radix <Theme> subtree that
  // scopes the colour tokens. Portalling to document.body lands outside it and
  // renders a light panel in dark mode.
  const container =
    document.getElementById("portal-container") ?? document.body;

  return createPortal(
    <div
      aria-hidden="true"
      data-testid="mission-control-overlay"
      className="pointer-events-none fixed inset-0 z-[300] flex flex-col items-center justify-center gap-[2.5vh] bg-(--gray-1)/75 backdrop-blur-md"
    >
      {/* The logo-only variant reserves vertical room for a wordmark it isn't
          drawing, so crop to the logomark's own 52:28 box — otherwise that dead
          space reads as a lopsided gap above the title. */}
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
