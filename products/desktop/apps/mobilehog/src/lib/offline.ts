import { savedConversationsSchema } from "@posthog/core/offline/schemas";
import { dehydrate, hydrate, onlineManager } from "@tanstack/react-query";
import * as Network from "expo-network";
import { useEffect } from "react";
import { AppState } from "react-native";
import { create } from "zustand";
import { getAccountQueryClient } from "@/lib/accountLifecycle";
import { sessionIdentity, useAuth } from "@/lib/auth";
import { useSessions } from "@/lib/session";
import { deviceWorkspace, WEEK } from "@/lib/storage";

export const useConnectivity = create<{ online: boolean }>(() => ({
  online: true,
}));

export function useOfflineWorkspace(): void {
  const identity = useAuth(sessionIdentity);
  const signedIn = useAuth((state) => !!state.session);
  useEffect(() => {
    const update = (state: Network.NetworkState): void => {
      const online =
        state.isConnected !== false && state.isInternetReachable !== false;
      useConnectivity.setState({ online });
      onlineManager.setOnline(online);
      if (online) useSessions.getState().reconnect();
    };
    void Network.getNetworkStateAsync()
      .then(update)
      .catch(() => {});
    const subscription = Network.addNetworkStateListener(update);
    return () => subscription.remove();
  }, []);
  useEffect(() => {
    if (!signedIn) return;
    const workspace = deviceWorkspace();
    const client = getAccountQueryClient();
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let restored = false;
    const save = (): void => {
      if (!restored || !active || sessionIdentity() !== identity) return;
      const cache = dehydrate(client, {
        shouldDehydrateQuery: (query) =>
          query.state.status === "success" &&
          [
            "tasks",
            "reports",
            "activity",
            "models",
            "repositories",
            "current-user",
          ].includes(String(query.queryKey[0])),
      });
      cache.mutations = [];
      cache.queries = cache.queries
        .filter((query) => JSON.stringify(query).length < 200_000)
        .sort((a, b) => b.state.dataUpdatedAt - a.state.dataUpdatedAt)
        .slice(0, 30);
      void workspace.write("query-cache", cache).catch(() => {});
      const sessions = Object.values(useSessions.getState().sessions)
        .filter((s) => s.runId)
        .slice(-20)
        .map((session) => ({
          taskId: session.taskId,
          runId: session.runId,
          blocks: session.blocks
            .flatMap((block) =>
              (block.kind === "user" || block.kind === "agent") &&
              block.text.length < 50_000
                ? [{ ...block, attachments: undefined }]
                : [],
            )
            .slice(-100),
        }));
      while (JSON.stringify(sessions).length > 2_000_000) sessions.shift();
      void workspace.write("conversations", sessions).catch(() => {});
    };
    const schedule = (): void => {
      if (timer) clearTimeout(timer);
      timer = setTimeout(save, 500);
    };
    void Promise.all([
      workspace.read<ReturnType<typeof dehydrate>>("query-cache", WEEK),
      workspace.read<
        Array<{
          taskId: string;
          runId: string;
          blocks: import("@/lib/transcript").Block[];
        }>
      >("conversations", WEEK),
    ])
      .then(([cache, conversations]) => {
        if (!active) return;
        if (cache && Array.isArray(cache.queries))
          hydrate(client, { ...cache, mutations: [] });
        const result = savedConversationsSchema.safeParse(conversations);
        if (result.success)
          for (const conversation of result.data)
            useSessions.getState().restore(conversation);
      })
      .catch(() => {})
      .finally(() => {
        restored = true;
      });
    const stopQueries = client.getQueryCache().subscribe(schedule);
    const stopSessions = useSessions.subscribe(schedule);
    const state = AppState.addEventListener("change", (value) => {
      if (value !== "active") save();
    });
    return () => {
      save();
      active = false;
      if (timer) clearTimeout(timer);
      stopQueries();
      stopSessions();
      state.remove();
    };
  }, [identity, signedIn]);
}
