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

export function deriveSessionViewState(
  session: AgentSession | undefined,
  task: Task,
  workspace: Workspace | null,
  isCloud: boolean,
): SessionViewState {
  // The live session knows it is cloud before the workspace query or `latest_run`
  // metadata lands, so trust either source.
  const effectiveIsCloud = isCloud || session?.isCloud === true;
  const cloudStatus = resolveEffectiveCloudStatus(task, session);
  const isCloudRunTerminal = effectiveIsCloud && isTerminalStatus(cloudStatus);
  const isCloudRunNotTerminal = effectiveIsCloud && !isCloudRunTerminal;

  const hasError = session?.status === "error" && !session?.idleKilled;
  const isRunning = effectiveIsCloud
    ? !hasError
    : session?.status === "connected";

  const events = session?.events ?? [];
  const isPromptPending = session?.isPromptPending ?? false;
  const promptStartedAt = session?.promptStartedAt;

  const isNewSessionWithInitialPrompt =
    !task.latest_run?.id && !!task.description;
  const isResumingExistingSession = !!task.latest_run?.id;
  const isHydratingEmptyTranscript =
    effectiveIsCloud &&
    events.length === 0 &&
    (session?.isHydratingTranscript ?? false);
  const isInitializing = effectiveIsCloud
    ? isHydratingEmptyTranscript ||
      (!hasError &&
        (!session || (events.length === 0 && isCloudRunNotTerminal)))
    : !session ||
      (session.status === "connecting" && events.length === 0) ||
      (session.status === "connected" &&
        events.length === 0 &&
        (isPromptPending ||
          isNewSessionWithInitialPrompt ||
          isResumingExistingSession));

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
