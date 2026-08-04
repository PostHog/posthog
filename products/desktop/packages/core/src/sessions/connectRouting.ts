import type { SessionStatus } from "@posthog/shared";

export type LocalConnectRoute =
  | { kind: "no-auth" }
  | { kind: "resume-existing"; taskRunId: string; logUrl: string }
  | { kind: "create-new" };

export function routeLocalConnect(input: {
  hasAuth: boolean;
  latestRunId?: string | null;
  latestRunLogUrl?: string | null;
}): LocalConnectRoute {
  if (!input.hasAuth) {
    return { kind: "no-auth" };
  }
  if (input.latestRunId && input.latestRunLogUrl) {
    return {
      kind: "resume-existing",
      taskRunId: input.latestRunId,
      logUrl: input.latestRunLogUrl,
    };
  }
  return { kind: "create-new" };
}

export const OFFLINE_SESSION_MESSAGE =
  "No internet connection. Connect when you're back online.";

export interface AutoRetryFinalState {
  status: Extract<SessionStatus, "disconnected" | "error">;
  errorTitle?: string;
  errorMessage: string;
}

export function computeAutoRetryFinalState(input: {
  wentOffline: boolean;
  lastRetryMessage: string;
  originalMessage: string;
}): AutoRetryFinalState {
  if (input.wentOffline) {
    return {
      status: "disconnected",
      errorTitle: undefined,
      errorMessage: OFFLINE_SESSION_MESSAGE,
    };
  }
  return {
    status: "error",
    errorTitle: "Failed to connect",
    errorMessage: input.lastRetryMessage || input.originalMessage,
  };
}
