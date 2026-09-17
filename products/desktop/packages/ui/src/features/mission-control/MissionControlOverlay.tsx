import { Badge } from "@posthog/quill";
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
      let revealFrame = 0;
      const mountedFrame = requestAnimationFrame(() => {
        revealFrame = requestAnimationFrame(() => setVisible(true));
      });
      return () => {
        cancelAnimationFrame(mountedFrame);
        cancelAnimationFrame(revealFrame);
      };
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
      className={`pointer-events-none fixed inset-0 z-[300] flex flex-col items-center justify-center gap-[2.5vh] bg-(--gray-1)/10 backdrop-blur-sm transition-opacity duration-150 ease-out motion-reduce:transition-none ${visible ? "opacity-100" : "opacity-0"}`}
    >
      <div className="w-[min(18vw,160px)] [&>svg]:h-auto [&>svg]:w-full">
        <LogosLandscape wordmark={false} />
      </div>
      <p className="font-semibold text-(--gray-12) text-[clamp(16px,2.2vw,28px)] leading-none tracking-tight">
        PostHog Desktop
      </p>
      {import.meta.env.DEV && (
        // Sized off the viewport like the rest of the overlay so it stays
        // readable in the Mission Control thumbnail.
        <Badge
          variant="destructive"
          className="-rotate-3 h-auto rounded-(--radius-3) border-4 border-current/40 border-dashed px-[clamp(20px,3.2vw,44px)] py-[clamp(10px,1.4vw,20px)] font-bold font-mono text-[clamp(22px,4vw,52px)] uppercase leading-none tracking-widest"
        >
          Development
        </Badge>
      )}
    </div>,
    container,
  );
}
