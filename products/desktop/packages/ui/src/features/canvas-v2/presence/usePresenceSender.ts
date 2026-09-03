import type { BoardPoint } from "@posthog/core/canvas-v2/boardGeometry";
import { useHostTRPCClient } from "@posthog/host-router/react";
import {
  CANVAS_V2_PRESENCE_INTERVAL_MS,
  CANVAS_V2_PRESENCE_MAX_SELECTED_IDS,
  type CanvasV2PresenceCaret,
  type CanvasV2Viewport,
} from "@posthog/shared";
import { useCallback, useEffect, useMemo, useRef } from "react";

export interface PresenceSenderHandle {
  /** This board view's id, so the stream can drop our own pings. */
  clientId: string;
  reportCursor: (world: BoardPoint | null) => void;
  reportSelection: (ids: readonly string[]) => void;
  reportViewport: (viewport: CanvasV2Viewport) => void;
  reportCaret: (caret: CanvasV2PresenceCaret | null) => void;
}

/**
 * Sends where this person points, looks, and what they hold. At most ten
 * pings a second while the pointer moves, and one more on every discrete
 * change, which keeps the board well inside the server's rate limit.
 */
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

  const send = useCallback((): void => {
    if (stopped.current) return;
    lastSentAt.current = Date.now();
    void client.canvasV2Stream.sendPresence
      .mutate({
        id: boardId,
        presence: {
          clientId,
          cursor: cursor.current,
          viewport: viewport.current,
          selectedIds: [...selectedIds.current].slice(
            0,
            CANVAS_V2_PRESENCE_MAX_SELECTED_IDS,
          ),
          carets: carets.current,
        },
      })
      // A dropped ping costs the others one frame of the cursor, nothing more.
      .catch(() => {});
  }, [boardId, client, clientId]);

  // A queued ping always sends through the current board, never a closed one.
  const sendRef = useRef(send);
  sendRef.current = send;

  const schedule = useCallback((immediate: boolean): void => {
    if (stopped.current) return;
    const waited = Date.now() - lastSentAt.current;
    if (immediate || waited >= CANVAS_V2_PRESENCE_INTERVAL_MS) {
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

  useEffect(() => {
    stopped.current = false;
    return () => {
      stopped.current = true;
      if (timer.current !== undefined) clearTimeout(timer.current);
      timer.current = undefined;
    };
  }, []);

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
      cursor.current = world;
      schedule(world === null);
    },
    [schedule],
  );

  const reportSelection = useCallback(
    (ids: readonly string[]): void => {
      selectedIds.current = ids;
      schedule(true);
    },
    [schedule],
  );

  const reportViewport = useCallback(
    (next: CanvasV2Viewport): void => {
      viewport.current = next;
      schedule(false);
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
      schedule(false);
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
