import {
  BoardPresenceTracker,
  type PresencePeer,
} from "@posthog/core/canvas-v2/boardPresence";
import type { CanvasV2Presence } from "@posthog/shared";
import { useCallback, useEffect, useMemo, useState } from "react";

/** How often a quiet person is checked for and dropped. */
const PRUNE_INTERVAL_MS = 2_000;

export interface BoardPeersHandle {
  peers: PresencePeer[];
  ingest: (presence: CanvasV2Presence) => void;
}

/**
 * The other people on the board, as their pings come in and time out. The
 * local client id carries the board, so a new board is a new set of people.
 */
export function useBoardPeers(localClientId: string): BoardPeersHandle {
  const [peers, setPeers] = useState<PresencePeer[]>([]);

  const tracker = useMemo(
    () =>
      new BoardPresenceTracker({
        localClientId,
        unknownName: "Someone",
        onChange: setPeers,
      }),
    [localClientId],
  );

  useEffect(() => {
    setPeers([]);
    const timer = setInterval(() => tracker.prune(), PRUNE_INTERVAL_MS);
    return () => {
      clearInterval(timer);
      tracker.clear();
    };
  }, [tracker]);

  const ingest = useCallback(
    (presence: CanvasV2Presence) => tracker.ingest(presence),
    [tracker],
  );

  return { peers, ingest };
}
