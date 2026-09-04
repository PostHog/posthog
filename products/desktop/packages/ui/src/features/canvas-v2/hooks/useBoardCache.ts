import type { BoardSyncState } from "@posthog/core/canvas-v2/boardSync";
import { useHostTRPCClient } from "@posthog/host-router/react";
import { useEffect } from "react";

/** Waits this long after the last change, so a burst writes the file once. */
const WRITE_DELAY_MS = 400;

/**
 * Keeps the local board file current. The agent's read tools open that file,
 * so without this write they see nothing.
 */
export function useBoardCache(boardId: string, state: BoardSyncState): void {
  const client = useHostTRPCClient();
  const { name, headSeq, snapshot, status } = state;

  useEffect(() => {
    if (status !== "synced") return;
    const timer = setTimeout(() => {
      void client.canvasV2Cache.write
        .mutate({
          boardId,
          payload: { boardId, name, headSeq, snapshot },
        })
        .catch(() => undefined);
    }, WRITE_DELAY_MS);
    return () => clearTimeout(timer);
  }, [boardId, client, name, headSeq, snapshot, status]);
}
