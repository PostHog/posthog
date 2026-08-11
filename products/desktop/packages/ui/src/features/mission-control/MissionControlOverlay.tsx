import LogosLandscape from "@posthog/ui/primitives/Logo";
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { useMissionControlStore } from "./missionControlStore";

const FADE_DURATION_MS = 150;

export function MissionControlOverlay() {
  const active = useMissionControlStore((state) => state.active);
  const [rendered, setRendered] = useState(active);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (active) {
      setRendered(true);
      const timeout = setTimeout(() => setVisible(true), 0);
      return () => clearTimeout(timeout);
    }

    setVisible(false);
    const timeout = setTimeout(() => setRendered(false), FADE_DURATION_MS);
    return () => clearTimeout(timeout);
  }, [active]);

  if (!rendered) return null;

  // Portalling to document.body would land outside the Radix <Theme> subtree
  // and render a light panel in dark mode.
  const container =
    document.getElementById("portal-container") ?? document.body;

  return createPortal(
    <div
      aria-hidden="true"
      data-testid="mission-control-overlay"
      className={`pointer-events-none fixed inset-0 z-[300] flex flex-col items-center justify-center gap-[2.5vh] bg-(--gray-1)/70 backdrop-blur-md transition-opacity duration-150 ease-out motion-reduce:transition-none ${visible ? "opacity-100" : "opacity-0"}`}
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
