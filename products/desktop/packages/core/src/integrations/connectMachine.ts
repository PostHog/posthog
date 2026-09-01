import { signalsConfigKeys } from "../inbox/inboxQuery";
import { githubInstallRequestKeys } from "./repositoryKeys";

export type ConnectState =
  | "idle"
  | "connecting"
  | "timed-out"
  | "error"
  | "pending";

export interface ConnectError {
  message: string;
  code: string | null;
}

export interface ConnectStatus {
  state: ConnectState;
  error: ConnectError | null;
}

export type ConnectAction =
  | { type: "begin" }
  | { type: "succeed" }
  | { type: "fail"; error: ConnectError }
  | { type: "pending" }
  | { type: "timeout" }
  | { type: "reset" };

export const CONNECT_INITIAL_STATUS: ConnectStatus = {
  state: "idle",
  error: null,
};

export function connectReducer(
  status: ConnectStatus,
  action: ConnectAction,
): ConnectStatus {
  switch (action.type) {
    case "begin":
      return { state: "connecting", error: null };
    case "succeed":
      return { state: "idle", error: null };
    case "fail":
      return { state: "error", error: action.error };
    // GitHub handed the install to an org owner: the flow ended, but not in failure.
    case "pending":
      return { state: "pending", error: null };
    case "timeout":
      return { state: "timed-out", error: status.error };
    case "reset":
      return { state: "idle", error: null };
    default:
      return status;
  }
}

export interface ConnectFlags {
  isConnecting: boolean;
  isTimedOut: boolean;
  hasError: boolean;
  isPending: boolean;
}

export function deriveConnectFlags(state: ConnectState): ConnectFlags {
  return {
    isConnecting: state === "connecting",
    isTimedOut: state === "timed-out",
    hasError: state === "error",
    isPending: state === "pending",
  };
}

export function toConnectError(
  error: unknown,
  fallbackMessage: string,
): ConnectError {
  return {
    message: error instanceof Error ? error.message : fallbackMessage,
    code: null,
  };
}

export function githubInvalidationKeys(
  projectId: number | null = null,
): ReadonlyArray<ReadonlyArray<unknown>> {
  const keys: ReadonlyArray<unknown>[] = [];
  if (projectId !== null) {
    keys.push(["integrations", projectId]);
  }
  keys.push(["integrations", "list"]);
  keys.push(["user-github-integrations"]);
  keys.push(["github_login"]);
  keys.push([...githubInstallRequestKeys.all]);
  return keys;
}

export function slackInvalidationKeys(): ReadonlyArray<ReadonlyArray<unknown>> {
  // The autonomy config caches slack_notification_integration_id; connecting or
  // disconnecting a workspace changes it server-side, so refresh it too.
  return [
    ["integrations", "list"],
    ["integrations"],
    [...signalsConfigKeys.userAutonomyConfig],
  ];
}
