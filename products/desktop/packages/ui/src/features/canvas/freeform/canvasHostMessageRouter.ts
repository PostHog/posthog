import type {
  CanvasNavIntent,
  CanvasTextSelection,
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
const REPLAYABLE_SHORTCUT_KEYS = new Set([
  ",",
  "/",
  "[",
  "]",
  "{",
  "}",
  "1",
  "2",
  "3",
  "4",
  "5",
  "6",
  "7",
  "8",
  "9",
  "arrowdown",
  "arrowleft",
  "arrowright",
  "arrowup",
  "b",
  "i",
  "j",
  "k",
  "n",
  "t",
  "tab",
]);

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
  onTextSelection?: (selection: CanvasTextSelection | null) => void;
  onCommentActivate?: (id: string) => void;
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
  /** Whether the browser is currently processing a trusted user gesture. */
  hasUserActivation: () => boolean;
  /** open-external UX once the safety/activation/throttle gates pass — a confirm
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
      case "data-request": {
        // Canvas code is untrusted, so the host is what stops a canvas from
        // firing writes just by being loaded or rendered.
        if (
          (message.method === "actionInvoke" ||
            message.method === "agentRequest") &&
          !options.hasUserActivation()
        ) {
          options.post({
            channel: "posthog-canvas",
            type: "data-response",
            id: message.id,
            ok: false,
            error:
              message.method === "agentRequest"
                ? "Agent requests require a user action"
                : "Canvas actions require a user action",
          });
          break;
        }
        // agentRequest settles on a viewer's decision, not on I/O, so it stays
        // out of the shared slot pool: an approval dialog left open must not
        // starve the canvas's ordinary reads/writes. Its own bound is the
        // host's single-flight guard (one request awaiting approval at a time).
        const holdsSlot = message.method !== "agentRequest";
        if (
          (holdsSlot && activeDataRequests >= MAX_CONCURRENT_DATA_REQUESTS) ||
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
        if (holdsSlot) activeDataRequests += 1;
        try {
          const call = options
            .callbacks()
            .onDataRequest(message.method, message.payload);
          // agentRequest settles only when a viewer approves or cancels the
          // request in a dialog, which can take arbitrarily long. Racing it
          // against the generic timeout would tell the canvas the request
          // failed while the dialog is still open and a later approval could
          // still start the run, so it opts out of the timeout.
          const result =
            message.method === "agentRequest"
              ? await call
              : await Promise.race([
                  call,
                  new Promise<never>((_, reject) =>
                    setTimeout(
                      () => reject(new Error("Canvas data request timed out")),
                      DATA_REQUEST_TIMEOUT_MS,
                    ),
                  ),
                ]);
          options.post({
            channel: "posthog-canvas",
            type: "data-response",
            id: message.id,
            ok: true,
            result,
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
          if (holdsSlot) activeDataRequests -= 1;
        }
        break;
      }
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
      case "text-selection":
        options.callbacks().onTextSelection?.(message.selection);
        break;
      case "text-selection-cleared":
        options.callbacks().onTextSelection?.(null);
        break;
      case "comment-activate":
        options.callbacks().onCommentActivate?.(message.id);
        break;
      case "open-external":
        // Re-checks the schema's allowlist refine in case it ever drifts.
        if (!isSafePostHogUrl(message.url)) {
          options.onExternalOpenBlocked?.(message.url, "unsafe-url");
        } else if (!options.hasUserActivation()) {
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
      case "keydown": {
        if (!message.metaKey && !message.ctrlKey) break;
        if (!REPLAYABLE_SHORTCUT_KEYS.has(message.key.toLowerCase())) break;
        if (!(document.activeElement instanceof HTMLIFrameElement)) break;
        const init = {
          key: message.key,
          code: message.code,
          metaKey: message.metaKey,
          ctrlKey: message.ctrlKey,
          shiftKey: message.shiftKey,
          altKey: message.altKey,
        };
        document.dispatchEvent(new KeyboardEvent("keydown", init));
        document.dispatchEvent(new KeyboardEvent("keyup", init));
        break;
      }
      case "ready":
        options.callbacks().onReady?.();
        break;
    }
  };
}
