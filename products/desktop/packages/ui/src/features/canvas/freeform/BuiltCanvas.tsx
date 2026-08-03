import {
  type CanvasNavIntent,
  type CanvasToHostMessage,
  canvasToHostMessageSchema,
  type HostToCanvasMessage,
} from "@posthog/core/canvas/freeformSchemas";
import { isSafePostHogUrl } from "@posthog/shared";
import { logger } from "@posthog/ui/shell/logger";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { useLayoutEffect, useRef } from "react";

const log = logger.scope("built-canvas");
const EXTERNAL_OPEN_MIN_INTERVAL_MS = 1_000;
const MAX_CONCURRENT_DATA_REQUESTS = 8;
const MAX_DATA_REQUEST_BYTES = 64 * 1024;
const DATA_REQUEST_TIMEOUT_MS = 30_000;

function isBoundedPayload(payload: unknown): boolean {
  try {
    return JSON.stringify(payload).length <= MAX_DATA_REQUEST_BYTES;
  } catch {
    return false;
  }
}

export interface BuiltCanvasProps {
  artifactUrl: string;
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
  onDataRequest,
  onError,
  onReady,
  onRendered,
  onNavigate,
}: BuiltCanvasProps) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const lastExternalOpenRef = useRef(0);
  const activeDataRequestsRef = useRef(0);
  const latest = useRef({
    onDataRequest,
    onError,
    onReady,
    onRendered,
    onNavigate,
  });
  latest.current = { onDataRequest, onError, onReady, onRendered, onNavigate };

  useLayoutEffect(() => {
    const iframe = iframeRef.current;
    let artifactPort: MessagePort | null = null;
    let initialDocumentConnected = false;
    const post = (message: HostToCanvasMessage) =>
      artifactPort?.postMessage(message);

    const route = async (message: CanvasToHostMessage) => {
      switch (message.type) {
        case "data-request":
          if (
            activeDataRequestsRef.current >= MAX_CONCURRENT_DATA_REQUESTS ||
            !isBoundedPayload(message.payload)
          ) {
            post({
              channel: "posthog-canvas",
              type: "data-response",
              id: message.id,
              ok: false,
              error: "Canvas data request exceeds runtime limits",
            });
            break;
          }
          activeDataRequestsRef.current += 1;
          try {
            post({
              channel: "posthog-canvas",
              type: "data-response",
              id: message.id,
              ok: true,
              result: await Promise.race([
                latest.current.onDataRequest(message.method, message.payload),
                new Promise<never>((_, reject) =>
                  setTimeout(
                    () => reject(new Error("Canvas data request timed out")),
                    DATA_REQUEST_TIMEOUT_MS,
                  ),
                ),
              ]),
            });
          } catch (error) {
            post({
              channel: "posthog-canvas",
              type: "data-response",
              id: message.id,
              ok: false,
              error: error instanceof Error ? error.message : String(error),
            });
          } finally {
            activeDataRequestsRef.current -= 1;
          }
          break;
        case "error":
          log.warn("Built canvas error", { message: message.message });
          latest.current.onError?.(message.message, message.stack);
          break;
        case "rendered":
          latest.current.onRendered?.();
          break;
        case "navigate":
          latest.current.onNavigate?.(message.nav);
          break;
        case "open-external":
          if (
            isSafePostHogUrl(message.url) &&
            document.activeElement === iframeRef.current &&
            Date.now() - lastExternalOpenRef.current >=
              EXTERNAL_OPEN_MIN_INTERVAL_MS
          ) {
            lastExternalOpenRef.current = Date.now();
            if (
              window.confirm(
                `Open this link in your browser?\n\n${message.url}`,
              )
            ) {
              openExternalUrl(message.url);
            }
          }
          break;
        case "ready":
          latest.current.onReady?.();
          break;
      }
    };

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
