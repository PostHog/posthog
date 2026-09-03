import { useHostTRPCClient } from "@posthog/host-router/react";
import type { CanvasV2LogEntry, CanvasV2Presence } from "@posthog/shared";
import { logger } from "@posthog/ui/shell/logger";
import { useEffect, useRef } from "react";

const log = logger.scope("canvas-v2-stream");

export interface BoardStreamHandlers {
  onOp: (entry: CanvasV2LogEntry) => void;
  onPresence: (presence: CanvasV2Presence) => void;
  /** Redis dropped the ops after the last event id, so page them again. */
  onReload: (since: number) => void;
  onLive: (live: boolean) => void;
}

/**
 * The live board stream, held by the host. One subscription per open board:
 * ops arrive here instead of from the poll, and so does everybody's presence.
 */
export function useBoardStream(
  boardId: string,
  handlers: BoardStreamHandlers,
): void {
  const client = useHostTRPCClient();
  const latest = useRef(handlers);
  latest.current = handlers;

  useEffect(() => {
    const subscription = client.canvasV2Stream.onBoardEvent.subscribe(
      { id: boardId },
      {
        onData: (event) => {
          switch (event.type) {
            case "op":
              latest.current.onOp(event.entry);
              break;
            case "presence":
              latest.current.onPresence(event.presence);
              break;
            case "reload":
              latest.current.onReload(event.since);
              break;
            case "live":
              log.info("board stream live", {
                boardId,
                live: event.live,
              });
              latest.current.onLive(event.live);
              break;
            case "error":
              log.warn("board stream error", { message: event.message });
              break;
          }
        },
        onError: (error) => {
          log.warn("board stream dropped", { message: String(error) });
          latest.current.onLive(false);
        },
      },
    );

    return () => {
      subscription.unsubscribe();
      latest.current.onLive(false);
    };
  }, [boardId, client]);
}
