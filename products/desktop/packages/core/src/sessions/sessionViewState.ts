import type { AcpMessage, AgentSession, Workspace } from "@posthog/shared";
import {
  isTerminalStatus,
  type Task,
  type TaskRunStatus,
} from "@posthog/shared/domain-types";
import { resolveEffectiveCloudStatus } from "../task-detail/cloudRunState";

export interface SessionViewState {
  isCloudRunNotTerminal: boolean;
  isCloudRunTerminal: boolean;
  cloudStatus: TaskRunStatus | null;
  isRunning: boolean;
  hasError: boolean;
  events: AcpMessage[];
  isPromptPending: boolean;
  promptStartedAt: number | null | undefined;
  isInitializing: boolean;
  cloudBranch: string | null;
  errorTitle: string | undefined;
  errorMessage: string | undefined;
  errorRetryable: boolean | undefined;
}

export function deriveSessionViewState(
  session: AgentSession | undefined,
  task: Task,
  workspace: Workspace | null,
  isCloud: boolean,
): SessionViewState {
  const cloudStatus = resolveEffectiveCloudStatus(task, session);
  const isCloudRunTerminal = isCloud && isTerminalStatus(cloudStatus);
  const isCloudRunNotTerminal = isCloud && !isCloudRunTerminal;

  const hasError = session?.status === "error" && !session?.idleKilled;
  const handoffInProgress = session?.handoffInProgress ?? false;

  let isRunning = false;
  if (!handoffInProgress) {
    if (isCloud) {
      isRunning = !hasError;
    } else {
      isRunning = session?.status === "connected";
    }
  }

  const events = session?.events ?? [];
  const isPromptPending = session?.isPromptPending ?? false;
  const promptStartedAt = session?.promptStartedAt;

  const isNewSessionWithInitialPrompt =
    !task.latest_run?.id && !!task.description;
  const isResumingExistingSession = !!task.latest_run?.id;
  const isInitializing = isCloud
    ? !hasError && (!session || (events.length === 0 && isCloudRunNotTerminal))
    : !session ||
      (session.status === "connecting" && events.length === 0) ||
      (session.status === "connected" &&
        events.length === 0 &&
        (isPromptPending ||
          isNewSessionWithInitialPrompt ||
          isResumingExistingSession));

  const cloudBranch = isCloud
    ? (workspace?.baseBranch ?? task.latest_run?.branch ?? null)
    : null;

  return {
    isCloudRunNotTerminal,
    isCloudRunTerminal,
    cloudStatus,
    isRunning: !!isRunning,
    hasError,
    events,
    isPromptPending,
    promptStartedAt,
    isInitializing,
    cloudBranch,
    errorTitle: session?.errorTitle,
    errorMessage:
      session?.errorMessage ??
      (isCloud ? (session?.cloudErrorMessage ?? undefined) : undefined),
    errorRetryable: session?.errorRetryable,
  };
}
