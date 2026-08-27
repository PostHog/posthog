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

// The theme rides the fragment so the artifact runtime (a synchronous head
// script) applies `.dark` before first paint; the bridge port only connects
// at the load event, far too late to prevent a light flash. Fragments don't
// reach the server, so signed artifact URLs stay valid. Placement config
// rides the same fragment: the runtime freezes it as ph.config at boot.
function themedArtifactUrl(
  artifactUrl: string,
  theme: CanvasTheme,
  config?: Record<string, unknown>,
): string {
  const fragment = new URLSearchParams({ theme });
  if (config && Object.keys(config).length > 0) {
    fragment.set("config", JSON.stringify(config));
  }
  const themedUrl = new URL(artifactUrl);
  themedUrl.hash = fragment.toString();
  return themedUrl.href;
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
  // The URL fragment bakes in the mount-time theme only, because folding the
  // live theme in would reload the artifact on every toggle. Live changes go
  // over the port.
  const initialTheme = useRef(theme).current;
  const frameSrc = themedArtifactUrl(artifactUrl, initialTheme, config);
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

  // biome-ignore lint/correctness/useExhaustiveDependencies: a new artifact URL needs a fresh bridge even though the effect reads it only through the iframe.
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

    // The artifact loads directly in this (single) sandboxed frame with no
    // intermediate document, so one document boot and one handshake. The
    // runtime accepts `connect` from `event.source === parent`, which is the
    // app window. A SECOND load event means the artifact navigated its own
    // frame (sandboxed frames can self-navigate anywhere): the bridge is cut
    // AND the frame is blanked, so a foreign document neither gets data access
    // nor keeps rendering inside the app's chrome.
    let connected = false;
    const onLoad = () => {
      if (connected) {
        artifactPortRef.current?.close();
        artifactPortRef.current = null;
        if (iframe && iframe.src !== "about:blank") {
          log.warn(
            "Built canvas navigated its frame; bridge cut, frame blanked",
          );
          iframe.src = "about:blank";
        }
        return;
      }
      connected = true;
      const bridge = new MessageChannel();
      artifactPortRef.current = bridge.port1;
      artifactPortRef.current.addEventListener("message", onMessage);
      artifactPortRef.current.start();
      iframe?.contentWindow?.postMessage(
        { channel: "posthog-canvas", type: "connect" },
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

    iframe?.addEventListener("load", onLoad);
    return () => {
      iframe?.removeEventListener("load", onLoad);
      artifactPortRef.current?.close();
      artifactPortRef.current = null;
    };
  }, [frameSrc]);

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
      src={frameSrc}
      referrerPolicy="no-referrer"
      // Like FreeformCanvas: without a matching color-scheme the UA paints the
      // embedded documents' base canvas opaque white, flashing over a dark app
      // before the artifact's stylesheets and theme land.
      style={{ colorScheme: theme }}
      className="h-full w-full border-0 bg-background"
    />
  );
}
