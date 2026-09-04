import {
  type BoardApi,
  BoardSyncClient,
  type BoardSyncState,
} from "@posthog/core/canvas-v2/boardSync";
import { useEffect, useMemo } from "react";
import { useStore } from "zustand";

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
): { state: BoardSyncState; client: BoardSyncClient } {
  const client = useMemo(
    () => new BoardSyncClient(api, boardId),
    [api, boardId],
  );
  const state = useStore(client.store);

  useEffect(() => client.setActorUser(actorUser), [client, actorUser]);

  useEffect(() => {
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

  return { state, client };
}
