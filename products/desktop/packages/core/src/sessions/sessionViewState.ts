import type { AcpMessage, AgentSession, Workspace } from "@posthog/shared";
import {
  isTerminalStatus,
  type Task,
  type TaskRunStatus,
} from "@posthog/shared/domain-types";
import { resolveEffectiveCloudStatus } from "../task-detail/cloudRunState";

export interface SessionViewState {
  isCloud: boolean;
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

export interface SessionLifecycleState {
  isCloud: boolean;
  isCloudRunNotTerminal: boolean;
  isCloudRunTerminal: boolean;
  cloudStatus: TaskRunStatus | null;
  hasError: boolean;
  isInitializing: boolean;
}

export function deriveSessionLifecycleState(
  session: AgentSession | undefined,
  task: Task,
  isCloud: boolean,
  isTaskStarting = false,
): SessionLifecycleState {
  const effectiveIsCloud = isCloud || session?.isCloud === true;
  const taskRunId = task.latest_run?.id;
  const preferSessionRun =
    !!taskRunId && session?.resumeAncestorRunIds?.includes(taskRunId) === true;
  const activeTaskRunId = preferSessionRun
    ? session.taskRunId
    : (taskRunId ?? session?.taskRunId);
  const sessionMatchesActiveRun =
    !!session && !!activeTaskRunId && session.taskRunId === activeTaskRunId;
  const cloudStatus = preferSessionRun
    ? (session.cloudStatus ?? null)
    : resolveEffectiveCloudStatus(task, session);
  const isCloudRunTerminal = effectiveIsCloud && isTerminalStatus(cloudStatus);
  const hasError =
    sessionMatchesActiveRun &&
    session.status === "error" &&
    !session.idleKilled;
  const hasStarted =
    sessionMatchesActiveRun && session.firstPromptForRunId === activeTaskRunId;
  const expectsInitialPrompt =
    !!session &&
    (!!task.description || !!task.latest_run?.id || session.isPromptPending);

  let isInitializing = isTaskStarting;
  if (!isTaskStarting && !hasError && !isCloudRunTerminal && !hasStarted) {
    isInitializing = effectiveIsCloud;
    if (!effectiveIsCloud) {
      isInitializing =
        !session ||
        (sessionMatchesActiveRun &&
          (session.status === "connecting" ||
            (session.status === "connected" && expectsInitialPrompt)));
    }
  }

  return {
    isCloud: effectiveIsCloud,
    isCloudRunNotTerminal: effectiveIsCloud && !isCloudRunTerminal,
    isCloudRunTerminal,
    cloudStatus,
    hasError,
    isInitializing,
  };
}

export function deriveSessionViewState(
  session: AgentSession | undefined,
  task: Task,
  workspace: Workspace | null,
  isCloud: boolean,
  isTaskStarting = false,
): SessionViewState {
  // The live session knows it is cloud before the workspace query or `latest_run`
  // metadata lands, so trust either source.
  const lifecycle = deriveSessionLifecycleState(
    session,
    task,
    isCloud,
    isTaskStarting,
  );
  const {
    isCloud: effectiveIsCloud,
    isCloudRunNotTerminal,
    isCloudRunTerminal,
    cloudStatus,
    hasError,
    isInitializing,
  } = lifecycle;
  const isRunning = effectiveIsCloud
    ? !hasError
    : session?.status === "connected";

  const events = session?.events ?? [];
  const isPromptPending = session?.isPromptPending ?? false;
  const promptStartedAt = session?.promptStartedAt;

  const cloudBranch = effectiveIsCloud
    ? (workspace?.baseBranch ?? task.latest_run?.branch ?? null)
    : null;

  return {
    isCloud: effectiveIsCloud,
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
      (effectiveIsCloud
        ? (session?.cloudErrorMessage ?? undefined)
        : undefined),
    errorRetryable: session?.errorRetryable,
  };
}
