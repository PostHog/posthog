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

function buildArtifactHostDocument(artifactUrl: string): string {
  const artifactOrigin = new URL(artifactUrl).origin;
  const serializedArtifactUrl = JSON.stringify(artifactUrl).replaceAll(
    "<",
    "\\u003c",
  );

  return `<!doctype html>
<html>
<head>
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; frame-src ${artifactOrigin}">
<style>html,body,iframe{border:0;height:100%;margin:0;padding:0;width:100%}</style>
</head>
<body>
<script>
const artifactFrame = document.createElement("iframe");
artifactFrame.title = "Canvas artifact";
artifactFrame.sandbox = "allow-scripts";
artifactFrame.referrerPolicy = "no-referrer";
artifactFrame.src = ${serializedArtifactUrl};
let artifactLoaded = false;
let bridgePort;
const connect = () => {
  if (!artifactLoaded || !bridgePort) return;
  artifactFrame.contentWindow.postMessage(
    { channel: "posthog-canvas", type: "connect" },
    "*",
    [bridgePort],
  );
  bridgePort = undefined;
};
artifactFrame.addEventListener("load", () => {
  if (artifactLoaded) {
    parent.postMessage(
      { channel: "posthog-canvas-host", type: "artifact-navigation" },
      "*",
    );
    return;
  }
  artifactLoaded = true;
  connect();
});
window.addEventListener("message", (event) => {
  if (
    event.source !== parent ||
    event.data?.channel !== "posthog-canvas-host" ||
    event.data?.type !== "connect" ||
    !event.ports[0]
  ) return;
  bridgePort = event.ports[0];
  connect();
});
document.body.append(artifactFrame);
</script>
</body>
</html>`;
}

export interface BuiltCanvasProps {
  artifactUrl: string;
  /** The published manifest's frozen capabilities. Missing manifests deny all
   * data requests. */
  capabilities: CanvasCapabilities | undefined;
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
  const hostDocument = buildArtifactHostDocument(artifactUrl);
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

  // biome-ignore lint/correctness/useExhaustiveDependencies: a new host document needs a fresh bridge even though the effect reads it only through the iframe.
  useLayoutEffect(() => {
    const iframe = iframeRef.current;
    let artifactPort: MessagePort | null = null;

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
      hasUserActivation: () => navigator.userActivation?.isActive === true,
      // Built artifacts run arbitrary published code, so an external open asks
      // first even after the activation + throttle gates pass.
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
      if (artifactPort) return;
      const bridge = new MessageChannel();
      artifactPort = bridge.port1;
      artifactPort.addEventListener("message", onMessage);
      artifactPort.start();
      iframe?.contentWindow?.postMessage(
        { channel: "posthog-canvas-host", type: "connect" },
        "*",
        [bridge.port2],
      );
    };

    const onHostMessage = (event: MessageEvent) => {
      if (
        event.source !== iframe?.contentWindow ||
        event.data?.channel !== "posthog-canvas-host" ||
        event.data?.type !== "artifact-navigation"
      ) {
        return;
      }
      artifactPort?.close();
      artifactPort = null;
    };

    iframe?.addEventListener("load", onLoad);
    window.addEventListener("message", onHostMessage);
    return () => {
      iframe?.removeEventListener("load", onLoad);
      window.removeEventListener("message", onHostMessage);
      artifactPort?.close();
    };
  }, [hostDocument]);

  return (
    <iframe
      ref={iframeRef}
      title="Canvas"
      sandbox="allow-scripts"
      srcDoc={hostDocument}
      referrerPolicy="no-referrer"
      className="h-full w-full border-0 bg-background"
    />
  );
}
