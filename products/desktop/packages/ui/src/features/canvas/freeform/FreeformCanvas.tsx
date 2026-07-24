import {
  type CanvasAnalyticsConfig,
  type CanvasNavIntent,
  type CanvasToHostMessage,
  canvasToHostMessageSchema,
  type HostToCanvasMessage,
} from "@posthog/core/canvas/freeformSchemas";
import { isSafePostHogUrl } from "@posthog/shared";
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
import { buildSandboxDocument, type SandboxMode } from "./sandboxRuntime";

const log = logger.scope("freeform-canvas");

// Canvas code can post open-external without a gesture, so opens are limited.
const EXTERNAL_OPEN_MIN_INTERVAL_MS = 1_000;

export interface FreeformCanvasProps {
  /** The single-file React source to render. */
  code: string;
  /** edit = in-app authoring (full data shim); view = published/shared. */
  mode: SandboxMode;
  /**
   * Resolves a data-request from the canvas. The host owns the real token; this
   * runs the authenticated call and returns only the result. In view mode the
   * implementation must reject anything outside the frozen query allowlist.
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
  mode,
  onDataRequest,
  onError,
  onRendered,
  onNavigate,
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
  const lastExternalOpenRef = useRef(0);

  // The document is keyed on mode + the analytics host (which the CSP must open
  // for posthog-js), not on code: code is injected via `init`, so changing it
  // never reloads the iframe — it re-renders in place.
  const analyticsHost = analytics?.apiHost;
  const srcDoc = useMemo(
    () => buildSandboxDocument(mode, analyticsHost),
    [mode, analyticsHost],
  );

  // Latest props, read by the once-bound listener + the (stable) postInit.
  const latest = useRef({
    onDataRequest,
    onError,
    onRendered,
    onNavigate,
    code,
    mode,
    analytics,
    theme,
  });
  latest.current = {
    onDataRequest,
    onError,
    onRendered,
    onNavigate,
    code,
    mode,
    analytics,
    theme,
  };

  const postInit = useCallback(() => {
    const p = latest.current;
    iframeRef.current?.contentWindow?.postMessage(
      {
        channel: "posthog-canvas",
        type: "init",
        code: p.code,
        mode: p.mode,
        analytics: p.analytics,
        theme: p.theme,
      },
      "*",
    );
  }, []);

  // The iframe reloads only when srcDoc changes (mode / analytics host); on
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
    const post = (msg: HostToCanvasMessage) => {
      iframeRef.current?.contentWindow?.postMessage(msg, "*");
    };

    const route = async (msg: CanvasToHostMessage) => {
      switch (msg.type) {
        case "ready":
          readyRef.current = true;
          postInit();
          break;
        case "data-request": {
          try {
            const result = await latest.current.onDataRequest(
              msg.method,
              msg.payload,
            );
            post({
              channel: "posthog-canvas",
              type: "data-response",
              id: msg.id,
              ok: true,
              result,
            });
          } catch (err) {
            post({
              channel: "posthog-canvas",
              type: "data-response",
              id: msg.id,
              ok: false,
              error: err instanceof Error ? err.message : String(err),
            });
          }
          break;
        }
        case "error":
          log.warn("Freeform canvas error", { message: msg.message });
          latest.current.onError?.(msg.message, msg.stack);
          break;
        case "rendered":
          latest.current.onRendered?.();
          break;
        case "navigate":
          // msg.nav is already allowlist-validated by safeParse below.
          latest.current.onNavigate?.(msg.nav);
          break;
        case "open-external":
          // Re-checks the schema's allowlist refine in case it ever drifts.
          if (!isSafePostHogUrl(msg.url)) {
            log.warn("Blocked non-PostHog canvas external URL", {
              url: msg.url,
            });
          } else if (document.activeElement !== iframeRef.current) {
            // A real link click moves focus into the iframe; requiring focus
            // stops code from auto-opening URLs on load (e.g. thumbnails).
            log.warn("Ignored canvas external URL open without interaction", {
              url: msg.url,
            });
          } else if (
            Date.now() - lastExternalOpenRef.current <
            EXTERNAL_OPEN_MIN_INTERVAL_MS
          ) {
            log.warn("Throttled canvas external URL open", { url: msg.url });
          } else {
            lastExternalOpenRef.current = Date.now();
            openExternalUrl(msg.url);
          }
          break;
      }
    };

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

  // Re-send init when the code / mode / analytics change, if the iframe is ready.
  // NB: reference code/mode/analytics DIRECTLY here (not via postInit, which
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
        mode,
        analytics,
        theme: latest.current.theme,
      },
      "*",
    );
  }, [code, mode, analytics]);

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
      className="h-full w-full border-0 bg-background"
    />
  );
}
