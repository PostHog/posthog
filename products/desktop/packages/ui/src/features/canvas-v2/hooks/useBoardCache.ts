import type { BoardSyncState } from "@posthog/core/canvas-v2/boardSync";
import { resolveService } from "@posthog/di/container";
import {
  HOST_TRPC_CLIENT,
  type HostTrpcClient,
} from "@posthog/host-router/client";
import { useEffect, useRef } from "react";

/** Waits this long after the last change, so a burst writes the file once. */
const WRITE_DELAY_MS = 400;

/**
 * Keeps the local board file current. The agent's read tools open that file,
 * so without this write they see nothing.
 */
export function useBoardCache(boardId: string, state: BoardSyncState): void {
  const stateRef = useRef(state);
  stateRef.current = state;
  const writtenSeq = useRef(-1);

  useEffect(() => {
    writtenSeq.current = -1;
  }, []);

  useEffect(() => {
    if (state.status === "loading" && state.headSeq === 0) return;
    if (state.headSeq === writtenSeq.current) return;
    const timer = setTimeout(() => {
      const current = stateRef.current;
      writtenSeq.current = current.headSeq;
      void resolveService<HostTrpcClient>(HOST_TRPC_CLIENT)
        .canvasV2Cache.write.mutate({
          boardId,
          payload: {
            boardId,
            name: current.name,
            headSeq: current.headSeq,
            snapshot: current.snapshot,
          },
        })
        .catch(() => {
          // A cache write is a convenience: the board works without it.
          writtenSeq.current = -1;
        });
    }, WRITE_DELAY_MS);
    return () => clearTimeout(timer);
  }, [boardId, state.headSeq, state.status]);
}
