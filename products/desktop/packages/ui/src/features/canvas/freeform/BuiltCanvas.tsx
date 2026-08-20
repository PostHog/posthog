import { assertCanvasCapability } from "@posthog/core/canvas/canvasCapabilities";
import {
  type CanvasCommentHighlight,
  type CanvasNavIntent,
  type CanvasTextSelection,
  type CanvasTheme,
  canvasToHostMessageSchema,
} from "@posthog/core/canvas/freeformSchemas";
import type { CanvasCapabilities } from "@posthog/shared";
import { logger } from "@posthog/ui/shell/logger";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { useThemeStore } from "@posthog/ui/shell/themeStore";
import { useEffect, useLayoutEffect, useRef } from "react";
import { createCanvasHostMessageRouter } from "./canvasHostMessageRouter";
import { translateCanvasTextSelection } from "./canvasSelection";

const log = logger.scope("built-canvas");
const EMPTY_COMMENT_HIGHLIGHTS: CanvasCommentHighlight[] = [];

function buildArtifactHostDocument(
  artifactUrl: string,
  theme: CanvasTheme,
  config?: Record<string, unknown>,
): string {
  const artifactOrigin = new URL(artifactUrl).origin;
  // The theme rides the fragment so the artifact runtime (a synchronous head
  // script) applies `.dark` before first paint — the bridge port only connects
  // at the load event, far too late to prevent a light flash. Fragments don't
  // reach the server, so signed artifact URLs stay valid. Placement config
  // rides the same fragment: the runtime freezes it as ph.config at boot.
  const fragment = new URLSearchParams({ theme });
  if (config && Object.keys(config).length > 0) {
    fragment.set("config", JSON.stringify(config));
  }
  const themedUrl = new URL(artifactUrl);
  themedUrl.hash = fragment.toString();
  const serializedArtifactUrl = JSON.stringify(themedUrl.href).replaceAll(
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
  /** Per-placement settings, exposed to the artifact as ph.config (frozen at
   * boot). A changed config remounts the artifact. */
  config?: Record<string, unknown>;
  onError?: (message: string, stack?: string) => void;
  /** The artifact's runtime booted and posted "ready" — proof the signed URL
   * actually loaded (an expired URL never gets this far). */
  onReady?: () => void;
  onRendered?: () => void;
  onNavigate?: (intent: CanvasNavIntent) => void;
  onTextSelection?: (selection: CanvasTextSelection | null) => void;
  onCommentActivate?: (id: string) => void;
  commentHighlights?: CanvasCommentHighlight[];
  clearTextSelectionKey?: number;
}

export function BuiltCanvas({
  artifactUrl,
  capabilities,
  onDataRequest,
  config,
  onError,
  onReady,
  onRendered,
  onNavigate,
  onTextSelection,
  onCommentActivate,
  commentHighlights = EMPTY_COMMENT_HIGHLIGHTS,
  clearTextSelectionKey = 0,
}: BuiltCanvasProps) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  // Mirrors the host's light/dark theme, like FreeformCanvas — sent over the
  // artifact bridge port right after connect and again on every change.
  const theme = useThemeStore(
    (s): CanvasTheme => (s.isDarkMode ? "dark" : "light"),
  );
  const artifactPortRef = useRef<MessagePort | null>(null);
  // The srcDoc bakes in the mount-time theme only — folding the live theme in
  // would reload the artifact on every toggle. Live changes go over the port.
  const initialTheme = useRef(theme).current;
  const hostDocument = buildArtifactHostDocument(
    artifactUrl,
    initialTheme,
    config,
  );
  const latest = useRef({
    capabilities,
    onDataRequest,
    onError,
    onReady,
    onRendered,
    onNavigate,
    theme,
    onTextSelection,
    onCommentActivate,
    commentHighlights,
  });
  latest.current = {
    capabilities,
    onDataRequest,
    onError,
    onReady,
    onRendered,
    onNavigate,
    theme,
    onTextSelection,
    onCommentActivate,
    commentHighlights,
  };

  // biome-ignore lint/correctness/useExhaustiveDependencies: a new host document needs a fresh bridge even though the effect reads it only through the iframe.
  useLayoutEffect(() => {
    const iframe = iframeRef.current;

    const route = createCanvasHostMessageRouter({
      post: (message) => artifactPortRef.current?.postMessage(message),
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
        onReady: () => {
          artifactPortRef.current?.postMessage({
            channel: "posthog-canvas",
            type: "set-comment-highlights",
            highlights: latest.current.commentHighlights,
          });
          latest.current.onReady?.();
        },
        onRendered: () => latest.current.onRendered?.(),
        onNavigate: (intent) => latest.current.onNavigate?.(intent),
        onTextSelection: (selection) => {
          if (!selection) {
            latest.current.onTextSelection?.(null);
            return;
          }
          const frame = iframeRef.current?.getBoundingClientRect();
          latest.current.onTextSelection?.(
            translateCanvasTextSelection(selection, frame),
          );
        },
        onCommentActivate: (id) => latest.current.onCommentActivate?.(id),
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
      if (artifactPortRef.current) return;
      const bridge = new MessageChannel();
      artifactPortRef.current = bridge.port1;
      artifactPortRef.current.addEventListener("message", onMessage);
      artifactPortRef.current.start();
      iframe?.contentWindow?.postMessage(
        { channel: "posthog-canvas-host", type: "connect" },
        "*",
        [bridge.port2],
      );
      // Queued on the port until the artifact runtime starts it, so the first
      // themed paint happens before any data renders.
      artifactPortRef.current.postMessage({
        channel: "posthog-canvas",
        type: "set-theme",
        theme: latest.current.theme,
      });
    };

    const onHostMessage = (event: MessageEvent) => {
      if (
        event.source !== iframe?.contentWindow ||
        event.data?.channel !== "posthog-canvas-host" ||
        event.data?.type !== "artifact-navigation"
      ) {
        return;
      }
      artifactPortRef.current?.close();
      artifactPortRef.current = null;
    };

    iframe?.addEventListener("load", onLoad);
    window.addEventListener("message", onHostMessage);
    return () => {
      iframe?.removeEventListener("load", onLoad);
      window.removeEventListener("message", onHostMessage);
      artifactPortRef.current?.close();
      artifactPortRef.current = null;
    };
  }, [hostDocument]);

  // Live theme change: re-theme the running artifact without reloading it. On
  // mount the port is still null — the initial theme goes out in onLoad above.
  useEffect(() => {
    artifactPortRef.current?.postMessage({
      channel: "posthog-canvas",
      type: "set-theme",
      theme,
    });
  }, [theme]);

  useEffect(() => {
    artifactPortRef.current?.postMessage({
      channel: "posthog-canvas",
      type: "set-comment-highlights",
      highlights: commentHighlights,
    });
  }, [commentHighlights]);

  useEffect(() => {
    if (clearTextSelectionKey === 0) return;
    artifactPortRef.current?.postMessage({
      channel: "posthog-canvas",
      type: "clear-text-selection",
    });
  }, [clearTextSelectionKey]);

  return (
    <iframe
      ref={iframeRef}
      title="Canvas"
      sandbox="allow-scripts"
      srcDoc={hostDocument}
      referrerPolicy="no-referrer"
      // Like FreeformCanvas: without a matching color-scheme the UA paints the
      // embedded documents' base canvas opaque white, flashing over a dark app
      // before the artifact's stylesheets and theme land.
      style={{ colorScheme: theme }}
      className="h-full w-full border-0 bg-background"
    />
  );
}
