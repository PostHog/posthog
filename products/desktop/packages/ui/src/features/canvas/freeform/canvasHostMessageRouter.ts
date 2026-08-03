import type {
  CanvasNavIntent,
  CanvasToHostMessage,
  HostToCanvasMessage,
} from "@posthog/core/canvas/freeformSchemas";
import { isSafePostHogUrl } from "@posthog/shared";

// Canvas code can post open-external without a gesture, so opens are limited.
const EXTERNAL_OPEN_MIN_INTERVAL_MS = 1_000;
// Runtime guards on the canvas→host data bridge: canvas code is untrusted, so
// a runaway loop must not be able to pile up unbounded concurrent requests,
// ship oversized payloads, or hold a request slot forever.
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

export interface CanvasHostCallbacks {
  onDataRequest: (method: string, payload: unknown) => Promise<unknown>;
  onError?: (message: string, stack?: string) => void;
  onReady?: () => void;
  onRendered?: () => void;
  onNavigate?: (intent: CanvasNavIntent) => void;
}

export type ExternalOpenBlockReason =
  | "unsafe-url"
  | "no-interaction"
  | "throttled";

export interface CanvasHostMessageRouterOptions {
  /** Transport back into the canvas (window.postMessage or a MessagePort). */
  post: (message: HostToCanvasMessage) => void;
  /** Latest callbacks, read fresh per message, so the router can be created
   * once per mount without going stale. */
  callbacks: () => CanvasHostCallbacks;
  /** Whether the user has interacted with the frame. A real link click moves
   * focus into the iframe; requiring it stops canvas code from auto-opening
   * URLs on load (e.g. thumbnails). */
  isFrameFocused: () => boolean;
  /** open-external UX once the safety/focus/throttle gates pass — a confirm
   * dialog, a direct open, whatever the host warrants. */
  openExternal: (url: string) => void;
  /** A dropped open-external, with why (logging vs silence is caller policy). */
  onExternalOpenBlocked?: (
    url: string,
    reason: ExternalOpenBlockReason,
  ) => void;
}

// The host side of the canvas postMessage protocol, shared by the built-
// artifact iframe (BuiltCanvas) and the srcDoc sandbox (FreeformCanvas). The
// transport and the open-external UX differ per host; the message routing and
// the data-request runtime guards must not.
export function createCanvasHostMessageRouter(
  options: CanvasHostMessageRouterOptions,
): (message: CanvasToHostMessage) => Promise<void> {
  let lastExternalOpen = 0;
  let activeDataRequests = 0;

  return async (message) => {
    switch (message.type) {
      case "data-request":
        if (
          activeDataRequests >= MAX_CONCURRENT_DATA_REQUESTS ||
          !isBoundedPayload(message.payload)
        ) {
          options.post({
            channel: "posthog-canvas",
            type: "data-response",
            id: message.id,
            ok: false,
            error: "Canvas data request exceeds runtime limits",
          });
          break;
        }
        activeDataRequests += 1;
        try {
          options.post({
            channel: "posthog-canvas",
            type: "data-response",
            id: message.id,
            ok: true,
            result: await Promise.race([
              options
                .callbacks()
                .onDataRequest(message.method, message.payload),
              new Promise<never>((_, reject) =>
                setTimeout(
                  () => reject(new Error("Canvas data request timed out")),
                  DATA_REQUEST_TIMEOUT_MS,
                ),
              ),
            ]),
          });
        } catch (error) {
          options.post({
            channel: "posthog-canvas",
            type: "data-response",
            id: message.id,
            ok: false,
            error: error instanceof Error ? error.message : String(error),
          });
        } finally {
          activeDataRequests -= 1;
        }
        break;
      case "error":
        options.callbacks().onError?.(message.message, message.stack);
        break;
      case "rendered":
        options.callbacks().onRendered?.();
        break;
      case "navigate":
        // message.nav is already allowlist-validated by the schema parse.
        options.callbacks().onNavigate?.(message.nav);
        break;
      case "open-external":
        // Re-checks the schema's allowlist refine in case it ever drifts.
        if (!isSafePostHogUrl(message.url)) {
          options.onExternalOpenBlocked?.(message.url, "unsafe-url");
        } else if (!options.isFrameFocused()) {
          options.onExternalOpenBlocked?.(message.url, "no-interaction");
        } else if (
          Date.now() - lastExternalOpen <
          EXTERNAL_OPEN_MIN_INTERVAL_MS
        ) {
          options.onExternalOpenBlocked?.(message.url, "throttled");
        } else {
          lastExternalOpen = Date.now();
          options.openExternal(message.url);
        }
        break;
      case "ready":
        options.callbacks().onReady?.();
        break;
    }
  };
}
