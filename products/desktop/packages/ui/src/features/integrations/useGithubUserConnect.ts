import {
  CONNECT_INITIAL_STATUS,
  type ConnectError,
  type ConnectState,
  connectReducer,
  deriveConnectFlags,
  githubInvalidationKeys,
  toConnectError,
} from "@posthog/core/integrations/connectMachine";
import type { GithubConnectService } from "@posthog/core/integrations/githubConnectService";
import { GITHUB_CONNECT_SERVICE } from "@posthog/core/integrations/identifiers";
import { useService } from "@posthog/di/react";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { useIsOrgAdmin } from "@posthog/ui/features/auth/useOrgRole";
import { type QueryClient, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useReducer, useRef } from "react";
import { useGitHubIntegrationCallback } from "./useGitHubIntegrationCallback";

export { describeGithubConnectError } from "@posthog/core/integrations/connectErrors";

const IS_DEV = import.meta.env.DEV;

const POLL_INTERVAL_MS = 3_000;
const POLL_TIMEOUT_MS = 300_000;

export type GithubUserConnectState = ConnectState;
export type GithubUserConnectError = ConnectError;

interface Options {
  projectId: number | null;
}

interface Result {
  state: GithubUserConnectState;
  error: GithubUserConnectError | null;
  isConnecting: boolean;
  isTimedOut: boolean;
  hasError: boolean;
  connect: () => Promise<void>;
  reset: () => void;
}

export function invalidateGithubQueries(
  queryClient: QueryClient,
  projectId: number | null = null,
): void {
  for (const queryKey of githubInvalidationKeys(projectId)) {
    void queryClient.invalidateQueries({ queryKey: [...queryKey] });
  }
}

interface StateMachine {
  state: GithubUserConnectState;
  error: GithubUserConnectError | null;
  stateRef: React.MutableRefObject<GithubUserConnectState>;
  beginConnecting: () => void;
  finishWithError: (error: GithubUserConnectError) => void;
  reset: () => void;
  scheduleUserFlowTimeout: () => void;
  scheduleDevPolling: () => void;
}

function useConnectStateMachine(
  projectId: number | null,
  onConnected?: () => void,
): StateMachine {
  const queryClient = useQueryClient();
  const [status, dispatch] = useReducer(connectReducer, CONNECT_INITIAL_STATUS);
  const stateRef = useRef(status.state);
  stateRef.current = status.state;
  const onConnectedRef = useRef(onConnected);
  onConnectedRef.current = onConnected;
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const stopPolling = useCallback(() => {
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
    if (pollTimeoutRef.current) {
      clearTimeout(pollTimeoutRef.current);
      pollTimeoutRef.current = null;
    }
  }, []);

  const invalidate = useCallback(
    (pid: number | null) => invalidateGithubQueries(queryClient, pid),
    [queryClient],
  );

  useEffect(() => stopPolling, [stopPolling]);

  // Window-focus fallback: deep link from PostHog Cloud may not fire reliably,
  // so refetch when the user returns to the app while a connect is in flight.
  useEffect(() => {
    if (status.state !== "connecting") return;
    const onFocus = () => invalidate(projectId);
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [status.state, projectId, invalidate]);

  useGitHubIntegrationCallback({
    onSuccess: (callbackProjectId) => {
      stopPolling();
      dispatch({ type: "succeed" });
      invalidate(callbackProjectId ?? projectId);
      onConnectedRef.current?.();
    },
    onError: (cbError) => {
      stopPolling();
      dispatch({ type: "fail", error: cbError });
    },
    onTimedOut: () => {
      stopPolling();
      dispatch({ type: "timeout" });
      invalidate(projectId);
    },
  });

  const beginConnecting = useCallback(() => {
    stopPolling();
    dispatch({ type: "begin" });
  }, [stopPolling]);

  const finishWithError = useCallback(
    (e: GithubUserConnectError) => {
      stopPolling();
      dispatch({ type: "fail", error: e });
    },
    [stopPolling],
  );

  const reset = useCallback(() => {
    stopPolling();
    dispatch({ type: "reset" });
  }, [stopPolling]);

  const scheduleUserFlowTimeout = useCallback(() => {
    pollTimeoutRef.current = setTimeout(() => {
      stopPolling();
      dispatch({ type: "timeout" });
    }, POLL_TIMEOUT_MS);
  }, [stopPolling]);

  const scheduleDevPolling = useCallback(() => {
    if (!IS_DEV) return;
    pollTimerRef.current = setInterval(
      () => invalidate(projectId),
      POLL_INTERVAL_MS,
    );
  }, [invalidate, projectId]);

  return useMemo(
    () => ({
      state: status.state,
      error: status.error,
      stateRef,
      beginConnecting,
      finishWithError,
      reset,
      scheduleUserFlowTimeout,
      scheduleDevPolling,
    }),
    [
      status.state,
      status.error,
      beginConnecting,
      finishWithError,
      reset,
      scheduleUserFlowTimeout,
      scheduleDevPolling,
    ],
  );
}

function machineToResult(
  machine: StateMachine,
  connect: () => Promise<void>,
): Result {
  return {
    state: machine.state,
    error: machine.error,
    ...deriveConnectFlags(machine.state),
    connect,
    reset: machine.reset,
  };
}

export function useGithubUserConnect({ projectId }: Options): Result {
  const connectService = useService<GithubConnectService>(
    GITHUB_CONNECT_SERVICE,
  );
  const machine = useConnectStateMachine(projectId);

  const connect = useCallback(async () => {
    if (machine.stateRef.current === "connecting") return;
    if (projectId === null) return;
    machine.beginConnecting();
    try {
      await connectService.connectUser(projectId);
      machine.scheduleDevPolling();
      machine.scheduleUserFlowTimeout();
    } catch (e) {
      machine.finishWithError(
        toConnectError(e, "Failed to start GitHub connection"),
      );
    }
  }, [connectService, projectId, machine]);

  return machineToResult(machine, connect);
}

interface ConnectOptions extends Options {
  /** Whether `projectId` already has a team-level GitHub Integration. Required
   *  because the relevant project is not always the auth project (e.g.
   *  onboarding picks a project from a list). Admins on projects where this
   *  is `false` get the team-level OAuth flow (Cloud also seeds their
   *  `UserIntegration` in the same round-trip). */
  projectHasTeamIntegration: boolean | null;
  onConnected?: () => void;
}

/**
 * Single "Connect GitHub" button for surfaces that should respect the
 * team-vs-user distinction. Picks the team-level flow only for admins on
 * projects with no team integration yet; everyone else gets the user-level
 * flow. For purely user-scoped surfaces ("Add another GitHub org") use
 * `useGithubUserConnect` directly.
 */
export function useGithubConnect({
  projectId,
  projectHasTeamIntegration,
  onConnected,
}: ConnectOptions): Result {
  const connectService = useService<GithubConnectService>(
    GITHUB_CONNECT_SERVICE,
  );
  const cloudRegion = useAuthStateValue((s) => s.cloudRegion);
  const { isAdmin } = useIsOrgAdmin();
  const machine = useConnectStateMachine(projectId, onConnected);

  const connect = useCallback(async () => {
    if (machine.stateRef.current === "connecting") return;
    if (projectId === null) return;
    machine.beginConnecting();
    try {
      const outcome = await connectService.connect({
        projectId,
        isAdmin,
        projectHasTeamIntegration,
        cloudRegion,
      });
      if (outcome.flow === "user") {
        machine.scheduleDevPolling();
        machine.scheduleUserFlowTimeout();
      }
    } catch (e) {
      machine.finishWithError(
        toConnectError(e, "Failed to start GitHub connection"),
      );
    }
  }, [
    connectService,
    projectId,
    isAdmin,
    projectHasTeamIntegration,
    cloudRegion,
    machine,
  ]);

  return machineToResult(machine, connect);
}
