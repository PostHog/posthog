import { resolveService } from "@posthog/di/container";
import {
  HOST_TRPC_CLIENT,
  type HostTrpcClient,
} from "@posthog/host-router/client";
import {
  type BoardFrameToHostMessage,
  boardFrameToHostMessageSchema,
  CANVAS_V2_CHANNEL,
  CANVAS_V2_STATE_KEY_MAX_CHARS,
  type CanvasV2FrameCaret,
  type CanvasV2Op,
  type CanvasV2PresenceCaret,
  type CanvasV2Snapshot,
  type CanvasV2Theme,
  type CanvasV2Viewport,
  estimateJsonBytes,
  fragmentsEqual,
  type HostToBoardFrameMessage,
  isField,
  isReservedStateKey,
  isSafePostHogUrl,
} from "@posthog/shared";
import { BOARD_TOO_MANY_READS_AT_ONCE } from "@posthog/ui/features/canvas-v2/canvasV2Copy";
import { spendBoardWrite } from "@posthog/ui/features/canvas-v2/runtime/canvasV2DataBridge";
import { fieldMessageValue } from "@posthog/ui/features/canvas-v2/runtime/canvasV2FieldMessages";
import { logger } from "@posthog/ui/shell/logger";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { useHostCapabilities } from "@posthog/ui/shell/useHostCapabilities";
import type { QueryClient } from "@tanstack/react-query";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  boardFramePolicy,
  buildBoardFrameDocument,
} from "./boardFrameDocument";
import {
  type BoardFrameElement,
  listenToBoardFrame,
  sendToBoardFrame,
} from "./boardFrameElement";
import {
  type CanvasV2DataBridgeContext,
  handleCanvasV2DataRequest,
} from "./canvasV2DataBridge";

const log = logger.scope("canvas-v2-frame");

// Fragment code is untrusted, so a runaway loop must not pile up requests,
// ship oversized payloads, or hold a slot forever.
const MAX_PENDING_DATA_REQUESTS = 200;
const MAX_DATA_REQUEST_BYTES = 64 * 1024;
const DATA_REQUEST_TIMEOUT_MS = 30_000;
const EXTERNAL_OPEN_MIN_INTERVAL_MS = 1_000;

export interface BoardFrameEvents {
  onExitFocus(): void;
  onReady(): void;
  onFragmentRendered(id: string): void;
  onFragmentError(id: string, message: string, stack?: string): void;
  onStateChanged(key: string, value: unknown): void;
  onWheel(e: Extract<BoardFrameToHostMessage, { type: "wheel" }>): void;
  onBackgroundPointer(
    e: Extract<BoardFrameToHostMessage, { type: "background-pointer" }>,
  ): void;
  onFragmentPointerDown(
    e: Extract<BoardFrameToHostMessage, { type: "fragment-pointer-down" }>,
  ): void;
  /** Where the pointer is inside the frame, in client coordinates. */
  onPointerMove(clientX: number, clientY: number): void;
  onPointerLeave(): void;
}

export interface UseBoardFrameOptions {
  boardId: string;
  frameElement: BoardFrameElement | null;
  theme: CanvasV2Theme;
  queryClient: QueryClient;
  getSnapshot: () => CanvasV2Snapshot;
  applyLocal: (ops: CanvasV2Op[], opIds?: string[]) => void;
  /** Where this person edits a field, for the next presence ping. */
  reportCaret: (caret: CanvasV2PresenceCaret | null) => void;
  events: BoardFrameEvents;
}

export interface BoardFrameHandle {
  srcDoc: string;
  documentReady: boolean;
  ready: boolean;
  post: (message: HostToBoardFrameMessage) => void;
  sendInit: (viewport: CanvasV2Viewport) => void;
  syncSnapshot: (prev: CanvasV2Snapshot | null, next: CanvasV2Snapshot) => void;
  setViewport: (viewport: CanvasV2Viewport) => void;
  setSelection: (ids: string[]) => void;
  setFocus: (id: string | null) => void;
  setBusy: (busy: boolean) => void;
  setCarets: (carets: CanvasV2FrameCaret[]) => void;
}

// Owns the host side of the board-frame protocol: one message listener for the
// frame's life, the data bridge with its runtime limits, and the minimal
// messages that keep the frame's fragments and state in step with the board.
export function useBoardFrame(options: UseBoardFrameOptions): BoardFrameHandle {
  const { frameElement } = options;
  const { vendoredCanvasModules: vendoredModules } = useHostCapabilities();
  const srcDoc = useMemo(
    () => buildBoardFrameDocument({ vendoredModules }),
    [vendoredModules],
  );
  const [documentReady, setDocumentReady] = useState(!vendoredModules);

  useEffect(() => {
    if (!vendoredModules) return;
    let cancelled = false;
    void resolveService<HostTrpcClient>(HOST_TRPC_CLIENT)
      .canvasV2Frame.registerDocument.mutate({
        html: srcDoc,
        csp: boardFramePolicy(true),
      })
      .then(() => {
        if (!cancelled) setDocumentReady(true);
      })
      .catch((error: unknown) => {
        log.error("Could not register the board frame document", { error });
      });
    return () => {
      cancelled = true;
    };
  }, [srcDoc, vendoredModules]);
  const [ready, setReady] = useState(false);
  const readyRef = useRef(false);

  const latest = useRef(options);
  latest.current = options;

  // State the frame told us about, so a snapshot sync does not echo it back.
  const fromFrame = useRef(new Map<string, string>());

  const postRaw = useCallback(
    (message: HostToBoardFrameMessage): void => {
      sendToBoardFrame(frameElement, message);
    },
    [frameElement],
  );

  const post = useCallback(
    (message: HostToBoardFrameMessage): void => {
      if (!readyRef.current) return;
      postRaw(message);
    },
    [postRaw],
  );

  const sendInit = useCallback(
    (viewport: CanvasV2Viewport): void => {
      const { theme, getSnapshot } = latest.current;
      const snapshot = getSnapshot();
      fromFrame.current.clear();
      postRaw({
        channel: CANVAS_V2_CHANNEL,
        type: "init",
        theme,
        viewport,
        fragments: snapshot.fragments,
        state: frameState(snapshot.state),
      });
    },
    [postRaw],
  );

  const syncSnapshot = useCallback(
    (prev: CanvasV2Snapshot | null, next: CanvasV2Snapshot): void => {
      const previousFragments = new Map(
        (prev?.fragments ?? []).map((fragment) => [fragment.id, fragment]),
      );
      for (const fragment of next.fragments) {
        const before = previousFragments.get(fragment.id);
        if (before && fragmentsEqual(before, fragment)) continue;
        post({
          channel: CANVAS_V2_CHANNEL,
          type: "upsert-fragment",
          fragment:
            before?.code === fragment.code
              ? { ...fragment, code: undefined }
              : fragment,
        });
      }
      const nextIds = new Set(next.fragments.map((fragment) => fragment.id));
      for (const id of previousFragments.keys()) {
        if (!nextIds.has(id)) {
          post({ channel: CANVAS_V2_CHANNEL, type: "remove-fragment", id });
        }
      }
      const prevState = prev?.state ?? {};
      const keys = new Set([
        ...Object.keys(prevState),
        ...Object.keys(next.state),
      ]);
      for (const key of keys) {
        const value = next.state[key] ?? null;
        if (value === (prevState[key] ?? null)) continue;
        const json = stableJson(value);
        if (stableJson(prevState[key] ?? null) === json) continue;
        if (fromFrame.current.get(key) === json) {
          fromFrame.current.delete(key);
          continue;
        }
        post({
          channel: CANVAS_V2_CHANNEL,
          type: "set-state",
          key,
          value: fieldMessageValue(value),
        });
      }
    },
    [post],
  );

  // Presence pings arrive ten times a second, so an unchanged list is dropped.
  const sentCarets = useRef("");
  const setCarets = useCallback(
    (carets: CanvasV2FrameCaret[]): void => {
      const json = stableJson(carets);
      if (json === sentCarets.current) return;
      sentCarets.current = json;
      post({ channel: CANVAS_V2_CHANNEL, type: "set-carets", carets });
    },
    [post],
  );

  const setViewport = useCallback(
    (viewport: CanvasV2Viewport): void => {
      post({ channel: CANVAS_V2_CHANNEL, type: "set-viewport", viewport });
    },
    [post],
  );

  const setSelection = useCallback(
    (ids: string[]): void => {
      post({ channel: CANVAS_V2_CHANNEL, type: "set-selection", ids });
    },
    [post],
  );

  const setFocus = useCallback(
    (id: string | null): void => {
      post({ channel: CANVAS_V2_CHANNEL, type: "set-focus", id });
    },
    [post],
  );

  const setBusy = useCallback(
    (busy: boolean): void => {
      post({ channel: CANVAS_V2_CHANNEL, type: "set-busy", busy });
    },
    [post],
  );

  // Bound during commit, before the browser runs the iframe's load task, so the
  // frame's one-shot "ready" cannot arrive before the listener exists.
  useLayoutEffect(() => {
    let activeRequests = 0;
    let lastExternalOpen = 0;

    const reply = (
      id: string,
      ok: boolean,
      result?: unknown,
      error?: string,
    ): void => {
      postRaw({
        channel: CANVAS_V2_CHANNEL,
        type: "data-response",
        id,
        ok,
        result,
        error,
      });
    };

    const runDataRequest = async (
      message: Extract<BoardFrameToHostMessage, { type: "data-request" }>,
    ): Promise<void> => {
      if (
        activeRequests >= MAX_PENDING_DATA_REQUESTS ||
        estimateJsonBytes(message.payload) >
          (message.method === "stateEditText"
            ? 2 * 1024 * 1024
            : MAX_DATA_REQUEST_BYTES)
      ) {
        reply(message.id, false, undefined, BOARD_TOO_MANY_READS_AT_ONCE);
        return;
      }
      activeRequests += 1;
      const { boardId, queryClient, getSnapshot, applyLocal, reportCaret } =
        latest.current;
      const ctx: CanvasV2DataBridgeContext = {
        boardId,
        queryClient,
        getSnapshot,
        applyLocal,
        reportCaret,
      };
      try {
        const result = await Promise.race([
          handleCanvasV2DataRequest(message.method, message.payload, ctx),
          new Promise<never>((_, rejectRequest) =>
            setTimeout(
              () => rejectRequest(new Error("Data request timed out")),
              DATA_REQUEST_TIMEOUT_MS,
            ),
          ),
        ]);
        reply(message.id, true, result);
      } catch (error) {
        reply(
          message.id,
          false,
          undefined,
          error instanceof Error ? error.message : String(error),
        );
      } finally {
        activeRequests -= 1;
      }
    };

    const route = (message: BoardFrameToHostMessage): void => {
      const events = latest.current.events;
      switch (message.type) {
        case "ready":
          readyRef.current = true;
          setReady(true);
          events.onReady();
          break;
        case "exit-focus":
          events.onExitFocus();
          break;
        case "fragment-rendered":
          events.onFragmentRendered(message.id);
          break;
        case "fragment-error":
          events.onFragmentError(message.id, message.message, message.stack);
          break;
        case "state-changed":
          if (
            isReservedStateKey(message.key) ||
            message.key.length > CANVAS_V2_STATE_KEY_MAX_CHARS
          ) {
            log.warn("Refused a fragment state key");
            break;
          }
          if (!spendBoardWrite(options.boardId)) {
            log.warn("Paused a fragment that writes shared state too fast");
            break;
          }
          // A mergeable field changes only through the field bridge.
          if (isField(latest.current.getSnapshot().state[message.key])) break;
          fromFrame.current.set(message.key, stableJson(message.value ?? null));
          events.onStateChanged(message.key, message.value);
          break;
        case "policy-violation":
          log.warn("A fragment tried a channel the board closes", {
            directive: message.directive,
            blocked: message.blocked,
          });
          break;
        case "data-request":
          void runDataRequest(message);
          break;
        case "wheel":
          events.onWheel(message);
          break;
        case "background-pointer":
          events.onBackgroundPointer(message);
          break;
        case "fragment-pointer-down":
          events.onFragmentPointerDown(message);
          break;
        case "pointer-move":
          events.onPointerMove(message.clientX, message.clientY);
          break;
        case "pointer-leave":
          events.onPointerLeave();
          break;
        case "open-external": {
          const now = Date.now();
          if (!isSafePostHogUrl(message.url)) {
            log.warn("Blocked non-PostHog fragment external URL");
          } else if (navigator.userActivation?.isActive !== true) {
            log.warn("Ignored fragment external URL open without interaction");
          } else if (now - lastExternalOpen < EXTERNAL_OPEN_MIN_INTERVAL_MS) {
            log.warn("Throttled fragment external URL open");
          } else {
            lastExternalOpen = now;
            openExternalUrl(message.url);
          }
          break;
        }
      }
    };

    if (!frameElement) return;
    return listenToBoardFrame(frameElement, (data) => {
      const parsed = boardFrameToHostMessageSchema.safeParse(data);
      if (!parsed.success) return;
      route(parsed.data);
    });
  }, [frameElement, postRaw, options.boardId]);

  // Re-theme in place: a fragment remount would reset its component state.
  useEffect(() => {
    post({
      channel: CANVAS_V2_CHANNEL,
      type: "set-theme",
      theme: options.theme,
    });
  }, [post, options.theme]);

  return {
    srcDoc,
    documentReady,
    ready,
    post,
    sendInit,
    syncSnapshot,
    setViewport,
    setSelection,
    setFocus,
    setBusy,
    setCarets,
  };
}

function frameState(state: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(state)) {
    out[key] = fieldMessageValue(value);
  }
  return out;
}

function stableJson(value: unknown): string {
  try {
    return JSON.stringify(value ?? null) ?? "null";
  } catch {
    return "null";
  }
}
