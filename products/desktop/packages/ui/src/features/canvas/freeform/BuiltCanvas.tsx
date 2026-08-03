import { assertCanvasCapability } from "@posthog/core/canvas/canvasCapabilities";
import {
  type CanvasNavIntent,
  canvasToHostMessageSchema,
} from "@posthog/core/canvas/freeformSchemas";
import type { CanvasCapabilities } from "@posthog/shared";
import { logger } from "@posthog/ui/shell/logger";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { useLayoutEffect, useRef } from "react";
import { createCanvasHostMessageRouter } from "./canvasHostMessageRouter";

const log = logger.scope("built-canvas");

export interface BuiltCanvasProps {
  artifactUrl: string;
  /**
   * View-mode data gate: the published manifest's frozen capabilities, which
   * every data request is asserted against. undefined = ungated — the
   * interactive/edit path (the author's own client keeps full data access
   * while iterating), or the transient window before a manifest has loaded.
   */
  capabilities?: CanvasCapabilities;
  onDataRequest: (method: string, payload: unknown) => Promise<unknown>;
  onError?: (message: string, stack?: string) => void;
  /** The artifact's runtime booted and posted "ready" — proof the signed URL
   * actually loaded (an expired URL never gets this far). */
  onReady?: () => void;
  onRendered?: () => void;
  onNavigate?: (intent: CanvasNavIntent) => void;
}

export function BuiltCanvas({
  artifactUrl,
  capabilities,
  onDataRequest,
  onError,
  onReady,
  onRendered,
  onNavigate,
}: BuiltCanvasProps) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const latest = useRef({
    capabilities,
    onDataRequest,
    onError,
    onReady,
    onRendered,
    onNavigate,
  });
  latest.current = {
    capabilities,
    onDataRequest,
    onError,
    onReady,
    onRendered,
    onNavigate,
  };

  useLayoutEffect(() => {
    const iframe = iframeRef.current;
    let artifactPort: MessagePort | null = null;
    let initialDocumentConnected = false;

    const route = createCanvasHostMessageRouter({
      post: (message) => artifactPort?.postMessage(message),
      callbacks: () => ({
        onDataRequest: (method, payload) => {
          // Gating lives here so every consumer of BuiltCanvas gets it by
          // default; the throw is routed back as a data-response error.
          assertCanvasCapability(latest.current.capabilities, method, payload);
          return latest.current.onDataRequest(method, payload);
        },
        onError: (message, stack) => {
          log.warn("Built canvas error", { message });
          latest.current.onError?.(message, stack);
        },
        onReady: () => latest.current.onReady?.(),
        onRendered: () => latest.current.onRendered?.(),
        onNavigate: (intent) => latest.current.onNavigate?.(intent),
      }),
      isFrameFocused: () => document.activeElement === iframeRef.current,
      // Built artifacts run arbitrary published code, so an external open asks
      // first even after the focus + throttle gates pass.
      openExternal: (url) => {
        if (window.confirm(`Open this link in your browser?\n\n${url}`)) {
          openExternalUrl(url);
        }
      },
    });

    const onMessage = (event: MessageEvent) => {
      const parsed = canvasToHostMessageSchema.safeParse(event.data);
      if (parsed.success) void route(parsed.data);
    };

    const onLoad = () => {
      if (initialDocumentConnected) {
        artifactPort?.close();
        artifactPort = null;
        return;
      }
      initialDocumentConnected = true;
      const bridge = new MessageChannel();
      artifactPort = bridge.port1;
      artifactPort.addEventListener("message", onMessage);
      artifactPort.start();
      iframe?.contentWindow?.postMessage(
        { channel: "posthog-canvas", type: "connect" },
        "*",
        [bridge.port2],
      );
    };

    iframe?.addEventListener("load", onLoad);
    return () => {
      iframe?.removeEventListener("load", onLoad);
      artifactPort?.close();
    };
  }, []);

  return (
    <iframe
      ref={iframeRef}
      title="Canvas"
      sandbox="allow-scripts"
      src={artifactUrl}
      referrerPolicy="no-referrer"
      className="h-full w-full border-0 bg-background"
    />
  );
}
