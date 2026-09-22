import {
  type CanvasAnalyticsConfig,
  type CanvasCommentHighlight,
  type CanvasNavIntent,
  type CanvasTextSelection,
  canvasToHostMessageSchema,
} from "@posthog/core/canvas/freeformSchemas";
import { logger } from "@posthog/ui/shell/logger";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { useThemeStore } from "@posthog/ui/shell/themeStore";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
} from "react";
import { createCanvasHostMessageRouter } from "./canvasHostMessageRouter";
import { translateCanvasTextSelection } from "./canvasSelection";
import { buildSandboxDocument } from "./sandboxRuntime";

const log = logger.scope("freeform-canvas");
const EMPTY_COMMENT_HIGHLIGHTS: CanvasCommentHighlight[] = [];

export interface FreeformCanvasProps {
  /** The single-file React source to render. */
  code: string;
  /**
   * Resolves a data-request from the canvas. The host owns the real token; this
   * runs the authenticated call and returns only the result. Ungated by design —
   * this sandbox only ever runs a canvas its own author is editing. A published
   * canvas renders in BuiltCanvas, which checks its build's capabilities first.
   */
  onDataRequest: (method: string, payload: unknown) => Promise<unknown>;
  /** Called when the canvas reports a compile/runtime error (self-repair loop). */
  onError?: (message: string, stack?: string) => void;
  /** Called once the canvas has rendered successfully (clears error state). */
  onRendered?: () => void;
  /**
   * Called when the canvas requests a host navigation. The intent is already
   * validated against the allowlist; this component stays channel-agnostic and
   * just forwards it — the caller maps it to actual routing.
   */
  onNavigate?: (intent: CanvasNavIntent) => void;
  onTextSelection?: (selection: CanvasTextSelection | null) => void;
  onCommentActivate?: (id: string) => void;
  commentHighlights?: CanvasCommentHighlight[];
  clearTextSelectionKey?: number;
  /**
   * Bootstrap config for in-iframe posthog-js (analytics + session replay).
   * Absent = no capture/replay. Only the PUBLIC key is here; the private token
   * never crosses into the iframe.
   */
  analytics?: CanvasAnalyticsConfig;
}

// Renders a freeform-React canvas inside a null-origin sandboxed iframe and
// brokers the postMessage protocol with it. The component never hands the iframe
// a JS object — only structured-clone messages cross the boundary.
export function FreeformCanvas({
  code,
  onDataRequest,
  onError,
  onRendered,
  onNavigate,
  onTextSelection,
  onCommentActivate,
  commentHighlights = EMPTY_COMMENT_HIGHLIGHTS,
  clearTextSelectionKey = 0,
  analytics,
}: FreeformCanvasProps) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  // The canvas mirrors the host's light/dark theme. Passed via `init` (not the
  // srcDoc) so a theme switch updates the running canvas in place, like `code`.
  const theme = useThemeStore((s) => (s.isDarkMode ? "dark" : "light"));
  // Whether the iframe has announced it's ready for `init`. A ref, not state: it
  // only gates an imperative postMessage and is never shown on screen, so it
  // shouldn't trigger re-renders.
  const readyRef = useRef(false);

  // The document is keyed on the analytics host (which the CSP must open for
  // posthog-js), not on code: code is injected via `init`, so changing it
  // never reloads the iframe — it re-renders in place.
  const analyticsHost = analytics?.apiHost;
  const srcDoc = useMemo(
    () => buildSandboxDocument(analyticsHost),
    [analyticsHost],
  );

  // Latest props, read by the once-bound listener + the (stable) postInit.
  const latest = useRef({
    onDataRequest,
    onError,
    onRendered,
    onNavigate,
    onTextSelection,
    onCommentActivate,
    code,
    analytics,
    theme,
    commentHighlights,
  });
  latest.current = {
    onDataRequest,
    onError,
    onRendered,
    onNavigate,
    onTextSelection,
    onCommentActivate,
    code,
    analytics,
    theme,
    commentHighlights,
  };

  const postInit = useCallback(() => {
    const p = latest.current;
    iframeRef.current?.contentWindow?.postMessage(
      {
        channel: "posthog-canvas",
        type: "init",
        code: p.code,
        analytics: p.analytics,
        theme: p.theme,
        highlights: p.commentHighlights,
      },
      "*",
    );
  }, []);

  // The iframe reloads only when srcDoc changes (the analytics host); on
  // reload it re-announces "ready", so mark it not-ready until then. Ref write
  // only — no state update, no extra render.
  // biome-ignore lint/correctness/useExhaustiveDependencies: srcDoc identity tracks a reload.
  useLayoutEffect(() => {
    readyRef.current = false;
  }, [srcDoc]);

  // Subscribed once for the component's life; reads latest props via the ref.
  // Layout effect (not passive): the listener must be attached during commit,
  // before the browser yields to the iframe's load task — otherwise the iframe's
  // one-shot "ready" (and early data-request/error) can fire before the
  // listener exists and be lost, leaving the canvas blank on a cold first open.
  useLayoutEffect(() => {
    const route = createCanvasHostMessageRouter({
      post: (msg) => {
        iframeRef.current?.contentWindow?.postMessage(msg, "*");
      },
      callbacks: () => ({
        // "ready" gates the imperative init handshake rather than a prop.
        onReady: () => {
          readyRef.current = true;
          postInit();
        },
        onDataRequest: latest.current.onDataRequest,
        onError: (message, stack) => {
          log.warn("Freeform canvas error", { message });
          latest.current.onError?.(message, stack);
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
      openExternal: openExternalUrl,
      // This host's policy is to log dropped opens rather than drop silently.
      onExternalOpenBlocked: (url, reason) => {
        if (reason === "unsafe-url") {
          log.warn("Blocked non-PostHog canvas external URL", { url });
        } else if (reason === "no-interaction") {
          log.warn("Ignored canvas external URL open without interaction", {
            url,
          });
        } else {
          log.warn("Throttled canvas external URL open", { url });
        }
      },
    });

    const onMessage = (event: MessageEvent) => {
      // A null-origin sandbox can't be trusted by origin, so identify the frame
      // by its window reference + our channel tag instead.
      if (event.source !== iframeRef.current?.contentWindow) return;
      const parsed = canvasToHostMessageSchema.safeParse(event.data);
      if (!parsed.success) return;
      void route(parsed.data);
    };

    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [postInit]);

  // Re-send init when the code / analytics change, if the iframe is ready.
  // NB: reference code/analytics DIRECTLY here (not via postInit, which
  // reads them off a ref) — otherwise the exhaustive-deps lint strips them from
  // the array as "unused" and the effect goes stale, never re-posting on change.
  // Theme is NOT a dep: a re-init remounts the app (new Blob module = fresh
  // component = reset state), so theme changes go through `set-theme` below
  // instead. init still carries the current theme so the next mount is correct.
  useEffect(() => {
    if (!readyRef.current) return;
    iframeRef.current?.contentWindow?.postMessage(
      {
        channel: "posthog-canvas",
        type: "init",
        code,
        analytics,
        theme: latest.current.theme,
        highlights: latest.current.commentHighlights,
      },
      "*",
    );
  }, [code, analytics]);

  useEffect(() => {
    if (!readyRef.current) return;
    iframeRef.current?.contentWindow?.postMessage(
      {
        channel: "posthog-canvas",
        type: "set-comment-highlights",
        highlights: commentHighlights,
      },
      "*",
    );
  }, [commentHighlights]);

  useEffect(() => {
    if (!readyRef.current || clearTextSelectionKey === 0) return;
    iframeRef.current?.contentWindow?.postMessage(
      { channel: "posthog-canvas", type: "clear-text-selection" },
      "*",
    );
  }, [clearTextSelectionKey]);

  // Live theme change: re-theme the running canvas in place (no remount), so a
  // host theme toggle — or an OS light/dark flip under "system" — preserves all
  // canvas state (filters, forms, scroll). Skipped until the iframe is ready;
  // the init above already carries the correct theme for the first render.
  useEffect(() => {
    if (!readyRef.current) return;
    iframeRef.current?.contentWindow?.postMessage(
      { channel: "posthog-canvas", type: "set-theme", theme },
      "*",
    );
  }, [theme]);

  return (
    <iframe
      ref={iframeRef}
      title="Canvas"
      // allow-scripts WITHOUT allow-same-origin = null origin = no access to host
      // cookies/storage/DOM. External navigation is brokered over postMessage;
      // do not add allow-popups or allow-same-origin.
      sandbox="allow-scripts"
      srcDoc={srcDoc}
      // Race-free init: by `load`, the iframe's module bootstrap has executed
      // (so its message listener is registered and "ready" already posted), so
      // posting init here reliably delivers the code — even if the one-shot
      // "ready" message was missed. Re-posting is idempotent (mountSeq dedupes).
      onLoad={() => {
        readyRef.current = true;
        postInit();
      }}
      // bg tracks the host theme so there's no white flash in dark mode before
      // the iframe paints; the canvas body uses the same --background token.
      // color-scheme matters as much as the background: without it the embedded
      // document's base canvas is painted white by the UA — which is what a
      // preview scrolling into view flashed before its stylesheets and the
      // first `init` (carrying the theme) arrived.
      style={{ colorScheme: theme }}
      className="h-full w-full border-0 bg-background"
    />
  );
}
