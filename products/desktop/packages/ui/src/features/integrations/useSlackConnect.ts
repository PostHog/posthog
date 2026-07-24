import {
  CONNECT_INITIAL_STATUS,
  type ConnectError,
  type ConnectState,
  connectReducer,
  deriveConnectFlags,
  slackInvalidationKeys,
  toConnectError,
} from "@posthog/core/integrations/connectMachine";
import { useHostTRPCClient } from "@posthog/host-router/react";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { type QueryClient, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useReducer, useRef } from "react";
import { useSlackIntegrationCallback } from "./useSlackIntegrationCallback";

const POLL_TIMEOUT_MS = 300_000;

export type SlackConnectState = ConnectState;
export type SlackConnectError = ConnectError;

interface Result {
  state: SlackConnectState;
  error: SlackConnectError | null;
  isConnecting: boolean;
  isTimedOut: boolean;
  hasError: boolean;
  connect: () => Promise<void>;
  reset: () => void;
}

function invalidateIntegrationQueries(queryClient: QueryClient): void {
  for (const queryKey of slackInvalidationKeys()) {
    void queryClient.invalidateQueries({ queryKey: [...queryKey] });
  }
}

/**
 * Drives the "Connect Slack workspace" button:
 *   - kicks off the main-process flow via `slackIntegration.startFlow`,
 *   - listens for the deep-link callback via `useSlackIntegrationCallback`,
 *   - refetches integration queries on success so the rest of the UI updates,
 *   - times out after 5 minutes and refetches as a fallback (a Slack admin who
 *     finishes the install in another browser still surfaces eventually).
 */
export function useSlackConnect(): Result {
  const client = useHostTRPCClient();
  const queryClient = useQueryClient();
  const cloudRegion = useAuthStateValue((s) => s.cloudRegion);
  const projectId = useAuthStateValue((s) => s.currentProjectId);

  const [status, dispatch] = useReducer(connectReducer, CONNECT_INITIAL_STATUS);
  const stateRef = useRef(status.state);
  stateRef.current = status.state;

  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const clearLocalTimeout = useCallback(() => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
  }, []);

  useEffect(() => clearLocalTimeout, [clearLocalTimeout]);

  // Window-focus fallback — the deep link can occasionally miss (browser
  // setting, OS prompt dismissed), so refetch when the user returns to the
  // app while a connect is in flight.
  useEffect(() => {
    if (status.state !== "connecting") return;
    const onFocus = () => invalidateIntegrationQueries(queryClient);
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [status.state, queryClient]);

  useSlackIntegrationCallback({
    onSuccess: () => {
      clearLocalTimeout();
      dispatch({ type: "succeed" });
      invalidateIntegrationQueries(queryClient);
    },
    onError: (cbError) => {
      clearLocalTimeout();
      dispatch({ type: "fail", error: cbError });
    },
    onTimedOut: () => {
      clearLocalTimeout();
      dispatch({ type: "timeout" });
      invalidateIntegrationQueries(queryClient);
    },
  });

  const reset = useCallback(() => {
    clearLocalTimeout();
    dispatch({ type: "reset" });
  }, [clearLocalTimeout]);

  const connect = useCallback(async () => {
    if (stateRef.current === "connecting") return;
    if (projectId === null || cloudRegion === null) return;
    clearLocalTimeout();
    dispatch({ type: "begin" });
    try {
      const res = await client.slackIntegration.startFlow.mutate({
        region: cloudRegion,
        projectId,
      });
      if (!res.success) {
        throw new Error(res.error ?? "Failed to start Slack connection");
      }
      timeoutRef.current = setTimeout(() => {
        dispatch({ type: "timeout" });
        invalidateIntegrationQueries(queryClient);
      }, POLL_TIMEOUT_MS);
    } catch (e) {
      clearLocalTimeout();
      dispatch({
        type: "fail",
        error: toConnectError(e, "Failed to start Slack connection"),
      });
    }
  }, [client, cloudRegion, projectId, clearLocalTimeout, queryClient]);

  return useMemo(
    () => ({
      state: status.state,
      error: status.error,
      ...deriveConnectFlags(status.state),
      connect,
      reset,
    }),
    [status.state, status.error, connect, reset],
  );
}
