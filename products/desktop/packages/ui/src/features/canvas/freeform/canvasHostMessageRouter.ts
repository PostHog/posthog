import type {
  CanvasNavIntent,
  CanvasTextSelection,
  CanvasToHostMessage,
  HostToCanvasMessage,
} from "@posthog/core/canvas/freeformSchemas";
import { isSafeGitHubPullRequestUrl, isSafePostHogUrl } from "@posthog/shared";

// Canvas code can post open-external without a gesture, so opens are limited.
const EXTERNAL_OPEN_MIN_INTERVAL_MS = 1_000;
// Runtime guards on the canvas→host data bridge: canvas code is untrusted, so
// a runaway loop must not be able to pile up unbounded concurrent requests,
// ship oversized payloads, or hold a request slot forever.
const MAX_CONCURRENT_DATA_REQUESTS = 8;
const MAX_CONCURRENT_CONNECTOR_REQUESTS = 8;
// A canvas that fans out more cards than there are slots is normal, so requests
// over the cap wait for a free slot instead of failing. The wait list is bounded
// too: a runaway loop must still hit a wall rather than grow without end.
const MAX_QUEUED_DATA_REQUESTS = 32;
const MAX_QUEUED_CONNECTOR_REQUESTS = 32;
const MAX_DATA_REQUEST_BYTES = 64 * 1024;
const DATA_REQUEST_TIMEOUT_MS = 30_000;
// The canvas runtime abandons a request 30s after it sends it, so a longer wait
// here would reach the canvas as a bare timeout and still run a query nobody
// waits for. Refuse earlier, while a retry can still finish inside that budget.
const MAX_QUEUE_WAIT_MS = 10_000;
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

// Concurrency slots with a bounded FIFO wait list. A released slot passes
// straight to the next waiter rather than going back to the pool, so a request
// that arrives while waiters are queued cannot jump ahead of them.
interface RequestSlots {
  active: number;
  readonly limit: number;
  readonly queueLimit: number;
  readonly waiting: Array<() => void>;
}

function createRequestSlots(limit: number, queueLimit: number): RequestSlots {
  return { active: 0, limit, queueLimit, waiting: [] };
}

function acquireSlot(slots: RequestSlots): Promise<boolean> {
  if (slots.active < slots.limit) {
    slots.active += 1;
    return Promise.resolve(true);
  }
  if (slots.waiting.length >= slots.queueLimit) return Promise.resolve(false);
  return new Promise<boolean>((resolve) => {
    const take = (): void => {
      clearTimeout(timer);
      resolve(true);
    };
    const timer = setTimeout(() => {
      const index = slots.waiting.indexOf(take);
      if (index > -1) slots.waiting.splice(index, 1);
      resolve(false);
    }, MAX_QUEUE_WAIT_MS);
    slots.waiting.push(take);
  });
}

function withRequestTimeout<T>(call: Promise<T>): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  return Promise.race([
    call,
    new Promise<never>((_, reject) => {
      timer = setTimeout(
        () => reject(new Error("Canvas data request timed out")),
        DATA_REQUEST_TIMEOUT_MS,
      );
    }),
  ]).finally(() => clearTimeout(timer));
}

function releaseSlot(slots: RequestSlots): void {
  const next = slots.waiting.shift();
  if (next) {
    next();
    return;
  }
  slots.active -= 1;
}

interface CanvasHostCallbacks {
  onDataRequest: (method: string, payload: unknown) => Promise<unknown>;
  onError?: (message: string, stack?: string) => void;
  onReady?: () => void;
  onRendered?: () => void;
  onNavigate?: (intent: CanvasNavIntent) => void;
  onTextSelection?: (selection: CanvasTextSelection | null) => void;
  onCommentActivate?: (id: string) => void;
}

type ExternalOpenBlockReason = "unsafe-url" | "no-interaction" | "throttled";

/** Why a data request was refused before it reached the host callback. */
export type CanvasDataRequestRejectReason =
  | "payload-too-large"
  | "data-queue-full"
  | "connector-queue-full"
  | "needs-user-action"
  | "agent-needs-user-action";

const REJECT_MESSAGES: Record<CanvasDataRequestRejectReason, string> = {
  "payload-too-large": "Canvas data request is over the 64KB payload limit",
  "data-queue-full": "Too many canvas data requests are already waiting",
  "connector-queue-full":
    "Too many canvas connector requests are already waiting",
  "needs-user-action": "Canvas actions require a user action",
  "agent-needs-user-action": "Agent requests require a user action",
};

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
  /** A refused data request, with why. Hosts use this to measure the limits. */
  onDataRequestRejected?: (
    reason: CanvasDataRequestRejectReason,
    method: string,
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
  const dataSlots = createRequestSlots(
    MAX_CONCURRENT_DATA_REQUESTS,
    MAX_QUEUED_DATA_REQUESTS,
  );
  const connectorSlots = createRequestSlots(
    MAX_CONCURRENT_CONNECTOR_REQUESTS,
    MAX_QUEUED_CONNECTOR_REQUESTS,
  );

  const refuse = (
    id: string,
    method: string,
    reason: CanvasDataRequestRejectReason,
  ): void => {
    options.onDataRequestRejected?.(reason, method);
    options.post({
      channel: "posthog-canvas",
      type: "data-response",
      id,
      ok: false,
      error: REJECT_MESSAGES[reason],
      retryable:
        reason === "data-queue-full" || reason === "connector-queue-full",
    });
  };

  const slotsFor = (method: string): RequestSlots | null => {
    // Approval waits must not consume ordinary read/write slots.
    // Connector calls have their own limit; agent requests are single-flight.
    if (method === "agentRequest") return null;
    return method === "connectorCall" ? connectorSlots : dataSlots;
  };

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
          refuse(
            message.id,
            message.method,
            message.method === "agentRequest"
              ? "agent-needs-user-action"
              : "needs-user-action",
          );
          break;
        }
        if (!isBoundedPayload(message.payload)) {
          refuse(message.id, message.method, "payload-too-large");
          break;
        }
        const slots = slotsFor(message.method);
        // A refusal here means the canvas stayed saturated for the whole wait,
        // so the request never ran and the canvas may send it again.
        if (slots && !(await acquireSlot(slots))) {
          refuse(
            message.id,
            message.method,
            message.method === "connectorCall"
              ? "connector-queue-full"
              : "data-queue-full",
          );
          break;
        }
        // The async wrapper turns a callback that throws on the spot, such as a
        // capability check, into a rejection the slot release can follow.
        const call = (async () =>
          options.callbacks().onDataRequest(message.method, message.payload))();
        // A timed-out request is reported to the canvas, but the call behind it
        // keeps running: no host passes an abort signal down to the query. The
        // slot therefore follows the call, not the report, so the cap counts
        // the work that is really in flight.
        if (slots) {
          const release = (): void => releaseSlot(slots);
          call.then(release, release);
        }
        try {
          // Approval dialogs can stay open longer than the I/O timeout.
          // Do not report a failure while a later approval can still run the call.
          const result =
            message.method === "agentRequest" ||
            message.method === "connectorCall"
              ? await call
              : await withRequestTimeout(call);
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
        if (
          (message.nav.target === "connect" ||
            message.nav.target === "compose-task" ||
            message.nav.target === "new-task") &&
          !options.hasUserActivation()
        )
          break;
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
        if (
          !isSafePostHogUrl(message.url) &&
          !isSafeGitHubPullRequestUrl(message.url)
        ) {
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
