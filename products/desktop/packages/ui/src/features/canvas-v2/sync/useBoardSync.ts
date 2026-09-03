import {
  type BoardApi,
  BoardSyncClient,
  type BoardSyncState,
} from "@posthog/core/canvas-v2/boardSync";
import { useEffect, useMemo, useRef, useState } from "react";

export interface BoardSyncActorUser {
  userId?: number;
  userName?: string;
}

/**
 * One sync client per board. The caller owns the transport, so this hook stays
 * free of tRPC.
 */
export function useBoardSync(
  boardId: string,
  api: BoardApi,
  actorUser?: BoardSyncActorUser,
): { state: BoardSyncState; client: BoardSyncClient | null } {
  const apiRef = useRef(api);
  apiRef.current = api;
  const actorRef = useRef(actorUser);
  actorRef.current = actorUser;
  const setStateRef = useRef<(next: BoardSyncState) => void>(() => {});

  // The transport is stable, so a new `api` object each render does not build a
  // second client for the same board.
  const stableApi = useMemo<BoardApi>(
    () => ({
      get: (id) => apiRef.current.get(id),
      opsSince: (id, since, limit) => apiRef.current.opsSince(id, since, limit),
      appendOps: (id, input) => apiRef.current.appendOps(id, input),
    }),
    [],
  );

  const client = useMemo(
    () =>
      new BoardSyncClient(stableApi, boardId, {
        actorUser: actorRef.current,
        onChange: (next) => setStateRef.current(next),
      }),
    [stableApi, boardId],
  );

  const [state, setState] = useState<BoardSyncState>(() => client.getState());

  useEffect(() => {
    setStateRef.current = setState;
    setState(client.getState());
    let live = true;
    void client.load().then(() => {
      if (live) client.start();
    });
    return () => {
      live = false;
      client.stop();
    };
  }, [client]);

  useEffect(() => {
    const onVisibility = (): void => {
      client.setVisible(document.visibilityState === "visible");
    };
    const onFocus = (): void => {
      client.setVisible(true);
      void client.poll();
    };
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("focus", onFocus);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("focus", onFocus);
    };
  }, [client]);

  // On the render after a board change, `state` still holds the old board.
  const current = state.boardId === boardId ? state : client.getState();
  return { state: current, client };
}
