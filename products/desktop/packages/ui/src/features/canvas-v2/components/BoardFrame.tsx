import { CANVAS_V2_FRAME_NAME } from "@posthog/shared";
import { BOARD_FRAME_TITLE } from "@posthog/ui/features/canvas-v2/canvasV2Copy";
import {
  type BoardFrameElement,
  createBoardWebview,
} from "@posthog/ui/features/canvas-v2/runtime/boardFrameElement";
import { type ReactElement, useEffect, useRef } from "react";

interface BoardFrameProps {
  onElement: (element: BoardFrameElement | null) => void;
  srcDoc: string;
  vendored: boolean;
  documentReady: boolean;
  inert: boolean;
  stopped: boolean;
  onHealth?: (health: BoardFrameHealth) => void;
}

export type BoardFrameHealth = "running" | "busy" | "gone";

export function BoardFrame({
  onElement,
  srcDoc,
  vendored,
  documentReady,
  inert,
  stopped,
  onHealth,
}: BoardFrameProps): ReactElement {
  const mountRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!vendored || !documentReady || stopped) return;
    const mount = mountRef.current;
    if (!mount) return;
    const webview = createBoardWebview();
    const busy = (): void => onHealth?.("busy");
    const running = (): void => onHealth?.("running");
    const gone = (): void => onHealth?.("gone");
    webview.addEventListener("unresponsive", busy);
    webview.addEventListener("responsive", running);
    webview.addEventListener("render-process-gone", gone);
    mount.appendChild(webview);
    onElement(webview);
    return () => {
      webview.removeEventListener("unresponsive", busy);
      webview.removeEventListener("responsive", running);
      webview.removeEventListener("render-process-gone", gone);
      webview.remove();
      onElement(null);
    };
  }, [vendored, documentReady, stopped, onElement, onHealth]);

  const inertClass = inert ? "pointer-events-none" : "";

  if (vendored) {
    return (
      <div
        ref={mountRef}
        title={BOARD_FRAME_TITLE}
        className={`absolute inset-0 h-full w-full ${inertClass}`}
      />
    );
  }

  return (
    <iframe
      ref={onElement}
      title={BOARD_FRAME_TITLE}
      name={CANVAS_V2_FRAME_NAME}
      sandbox="allow-scripts"
      allow=""
      referrerPolicy="no-referrer"
      srcDoc={srcDoc}
      className={`absolute inset-0 h-full w-full border-0 ${inertClass}`}
    />
  );
}
