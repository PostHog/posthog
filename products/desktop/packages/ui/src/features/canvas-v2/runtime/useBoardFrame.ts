import {
  type BoardFrameToHostMessage,
  boardFrameToHostMessageSchema,
  CANVAS_V2_CHANNEL,
  type CanvasV2Fragment,
  type CanvasV2Op,
  type CanvasV2Snapshot,
  type CanvasV2Theme,
  type CanvasV2Viewport,
  type HostToBoardFrameMessage,
  isSafePostHogUrl,
} from "@posthog/shared";
import { logger } from "@posthog/ui/shell/logger";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import type { QueryClient } from "@tanstack/react-query";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { buildBoardFrameDocument } from "./boardFrameDocument";
import {
  type CanvasV2DataBridgeContext,
  handleCanvasV2DataRequest,
} from "./canvasV2DataBridge";

const log = logger.scope("canvas-v2-frame");

// Fragment code is untrusted, so a runaway loop must not pile up requests,
// ship oversized payloads, or hold a slot forever.
const MAX_CONCURRENT_DATA_REQUESTS = 8;
const MAX_DATA_REQUEST_BYTES = 64 * 1024;
const DATA_REQUEST_TIMEOUT_MS = 30_000;
const EXTERNAL_OPEN_MIN_INTERVAL_MS = 1_000;

export interface BoardFrameEvents {
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
  iframeRef: React.RefObject<HTMLIFrameElement | null>;
  theme: CanvasV2Theme;
  queryClient: QueryClient;
  getSnapshot: () => CanvasV2Snapshot;
  applyLocal: (ops: CanvasV2Op[]) => void;
  events: BoardFrameEvents;
}

export interface BoardFrameHandle {
  srcDoc: string;
  ready: boolean;
  post: (message: HostToBoardFrameMessage) => void;
  sendInit: (viewport: CanvasV2Viewport) => void;
  syncSnapshot: (prev: CanvasV2Snapshot | null, next: CanvasV2Snapshot) => void;
  setViewport: (viewport: CanvasV2Viewport) => void;
  setSelection: (ids: string[]) => void;
}

// Owns the host side of the board-frame protocol: one message listener for the
// frame's life, the data bridge with its runtime limits, and the minimal
// messages that keep the frame's fragments and state in step with the board.
export function useBoardFrame(options: UseBoardFrameOptions): BoardFrameHandle {
  const { iframeRef } = options;
  const srcDoc = useMemo(() => buildBoardFrameDocument(), []);
  const [ready, setReady] = useState(false);
  const readyRef = useRef(false);

  const latest = useRef(options);
  latest.current = options;

  // State the frame told us about, so a snapshot sync does not echo it back.
  const fromFrame = useRef(new Map<string, string>());

  const postRaw = useCallback(
    (message: HostToBoardFrameMessage): void => {
      // Null origin: the frame is identified by its window, not by origin.
      iframeRef.current?.contentWindow?.postMessage(message, "*");
    },
    [iframeRef],
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
        state: snapshot.state,
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
        post({ channel: CANVAS_V2_CHANNEL, type: "upsert-fragment", fragment });
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
        const json = stableJson(value);
        if (stableJson(prevState[key] ?? null) === json) continue;
        if (fromFrame.current.get(key) === json) {
          fromFrame.current.delete(key);
          continue;
        }
        post({ channel: CANVAS_V2_CHANNEL, type: "set-state", key, value });
      }
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
        activeRequests >= MAX_CONCURRENT_DATA_REQUESTS ||
        !isBoundedPayload(message.payload)
      ) {
        reply(
          message.id,
          false,
          undefined,
          "Data request exceeds runtime limits",
        );
        return;
      }
      activeRequests += 1;
      const { boardId, queryClient, getSnapshot, applyLocal } = latest.current;
      const ctx: CanvasV2DataBridgeContext = {
        boardId,
        queryClient,
        getSnapshot,
        applyLocal,
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
        case "fragment-rendered":
          events.onFragmentRendered(message.id);
          break;
        case "fragment-error":
          events.onFragmentError(message.id, message.message, message.stack);
          break;
        case "state-changed":
          fromFrame.current.set(message.key, stableJson(message.value ?? null));
          events.onStateChanged(message.key, message.value);
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

    const onMessage = (event: MessageEvent): void => {
      if (event.source !== iframeRef.current?.contentWindow) return;
      const parsed = boardFrameToHostMessageSchema.safeParse(event.data);
      if (!parsed.success) return;
      route(parsed.data);
    };

    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [iframeRef, postRaw]);

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
    ready,
    post,
    sendInit,
    syncSnapshot,
    setViewport,
    setSelection,
  };
}

function fragmentsEqual(a: CanvasV2Fragment, b: CanvasV2Fragment): boolean {
  return (
    a.title === b.title &&
    a.x === b.x &&
    a.y === b.y &&
    a.w === b.w &&
    a.h === b.h &&
    a.z === b.z &&
    a.codeVersion === b.codeVersion &&
    a.code === b.code
  );
}

function stableJson(value: unknown): string {
  try {
    return JSON.stringify(value ?? null) ?? "null";
  } catch {
    return "null";
  }
}

function isBoundedPayload(payload: unknown): boolean {
  try {
    return JSON.stringify(payload ?? null).length <= MAX_DATA_REQUEST_BYTES;
  } catch {
    return false;
  }
}
