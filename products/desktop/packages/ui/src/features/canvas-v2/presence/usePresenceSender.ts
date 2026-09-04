import type { BoardPoint } from "@posthog/core/canvas-v2/boardGeometry";
import { useHostTRPCClient } from "@posthog/host-router/react";
import {
  CANVAS_V2_PRESENCE_INTERVAL_MS,
  CANVAS_V2_PRESENCE_MAX_SELECTED_IDS,
  type CanvasV2PresenceCaret,
  type CanvasV2Viewport,
} from "@posthog/shared";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
} from "react";

export interface PresenceSenderHandle {
  /** This board view's id, so the stream can drop our own pings. */
  clientId: string;
  reportCursor: (world: BoardPoint | null) => void;
  reportSelection: (ids: readonly string[]) => void;
  reportViewport: (viewport: CanvasV2Viewport) => void;
  reportCaret: (caret: CanvasV2PresenceCaret | null) => void;
}

export function usePresenceSender(boardId: string): PresenceSenderHandle {
  const client = useHostTRPCClient();
  // One id per board view: a second window is a second person on the board.
  const clientId = useMemo(
    () => `${boardId.slice(0, 8)}-${globalThis.crypto.randomUUID()}`,
    [boardId],
  );

  const cursor = useRef<BoardPoint | null>(null);
  const viewport = useRef<CanvasV2Viewport | null>(null);
  const selectedIds = useRef<readonly string[]>([]);
  const carets = useRef<CanvasV2PresenceCaret[]>([]);
  const lastSentAt = useRef(0);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const stopped = useRef(false);
  const inFlight = useRef(false);
  const dirty = useRef(false);
  const generation = useRef<symbol | null>(null);
  const scheduleRef = useRef<() => void>(() => {});

  const send = useCallback((): void => {
    if (stopped.current || inFlight.current) return;
    inFlight.current = true;
    dirty.current = false;
    const sendingGeneration = generation.current;
    lastSentAt.current = Date.now();
    void client.canvasV2Stream.sendPresence
      .mutate({
        id: boardId,
        presence: {
          clientId,
          cursor: cursor.current,
          viewport: viewport.current,
          selectedIds: [...selectedIds.current],
          carets: carets.current,
        },
      })
      // A dropped ping costs the others one frame of the cursor, nothing more.
      .catch(() => {})
      .finally(() => {
        if (sendingGeneration !== generation.current) return;
        inFlight.current = false;
        if (dirty.current) scheduleRef.current();
      });
  }, [boardId, client, clientId]);

  // A queued ping always sends through the current board, never a closed one.
  const sendRef = useRef(send);

  const schedule = useCallback((): void => {
    if (stopped.current) return;
    dirty.current = true;
    if (inFlight.current) return;
    const waited = Date.now() - lastSentAt.current;
    if (waited >= CANVAS_V2_PRESENCE_INTERVAL_MS) {
      if (timer.current !== undefined) {
        clearTimeout(timer.current);
        timer.current = undefined;
      }
      sendRef.current();
      return;
    }
    if (timer.current !== undefined) return;
    timer.current = setTimeout(() => {
      timer.current = undefined;
      sendRef.current();
    }, CANVAS_V2_PRESENCE_INTERVAL_MS - waited);
  }, []);

  useLayoutEffect(() => {
    sendRef.current = send;
    scheduleRef.current = schedule;
  }, [send, schedule]);

  useLayoutEffect(() => {
    generation.current = Symbol(clientId);
    stopped.current = false;
    cursor.current = null;
    viewport.current = null;
    selectedIds.current = [];
    carets.current = [];
    lastSentAt.current = 0;
    return () => {
      stopped.current = true;
      generation.current = null;
      inFlight.current = false;
      dirty.current = false;
      if (timer.current !== undefined) clearTimeout(timer.current);
      timer.current = undefined;
    };
  }, [clientId]);

  const reportCursor = useCallback(
    (world: BoardPoint | null): void => {
      const last = cursor.current;
      const same =
        (world === null && last === null) ||
        (world !== null &&
          last !== null &&
          Math.round(world.x) === Math.round(last.x) &&
          Math.round(world.y) === Math.round(last.y));
      if (same) return;
      cursor.current =
        world === null
          ? null
          : { x: Math.round(world.x), y: Math.round(world.y) };
      schedule();
    },
    [schedule],
  );

  const reportSelection = useCallback(
    (ids: readonly string[]): void => {
      const next = ids.slice(0, CANVAS_V2_PRESENCE_MAX_SELECTED_IDS);
      if (
        next.length === selectedIds.current.length &&
        next.every((id, index) => id === selectedIds.current[index])
      )
        return;
      selectedIds.current = next;
      schedule();
    },
    [schedule],
  );

  const reportViewport = useCallback(
    (next: CanvasV2Viewport): void => {
      const last = viewport.current;
      if (last?.x === next.x && last.y === next.y && last.zoom === next.zoom)
        return;
      viewport.current = next;
      schedule();
    },
    [schedule],
  );

  const reportCaret = useCallback(
    (caret: CanvasV2PresenceCaret | null): void => {
      const next = caret === null ? [] : [caret];
      const last = carets.current;
      const same =
        last.length === next.length &&
        last.every(
          (item, index) =>
            item.key === next[index].key &&
            item.anchor === next[index].anchor &&
            item.focus === next[index].focus,
        );
      if (same) return;
      carets.current = next;
      schedule();
    },
    [schedule],
  );

  // A person who alt-tabs away is no longer pointing at the board.
  useEffect(() => {
    const onBlur = (): void => reportCursor(null);
    window.addEventListener("blur", onBlur);
    return () => window.removeEventListener("blur", onBlur);
  }, [reportCursor]);

  // Stable, so a caller can report from an effect without pinging every render.
  return useMemo(
    () => ({
      clientId,
      reportCursor,
      reportSelection,
      reportViewport,
      reportCaret,
    }),
    [clientId, reportCursor, reportSelection, reportViewport, reportCaret],
  );
}
