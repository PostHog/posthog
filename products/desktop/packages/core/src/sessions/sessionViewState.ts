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
  isConnecting: boolean;
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

  const isHydratingEmptyTranscript =
    effectiveIsCloud &&
    events.length === 0 &&
    (session?.isHydratingTranscript ?? false);
  // Once a session object exists we dive straight into the thread + composer,
  // even while the agent is still connecting, so a full-panel spinner only
  // shows when there is genuinely nothing to render yet.
  const isInitializing = effectiveIsCloud
    ? isHydratingEmptyTranscript || !session
    : !session;

  // The window between a session existing and the agent handshake landing.
  // Cloud runs sit in "connecting" while the sandbox provisions; both hosts
  // flip to "connected" once the agent accepts messages. Terminal cloud runs
  // are done, not connecting.
  const isConnecting =
    !hasError &&
    !!session &&
    session.status !== "connected" &&
    !isCloudRunTerminal;

  const cloudBranch = effectiveIsCloud
    ? (workspace?.baseBranch ?? task.latest_run?.branch ?? null)
    : null;

  return {
    isCloud: effectiveIsCloud,
    isCloudRunNotTerminal,
    isCloudRunTerminal,
    cloudStatus,
    isRunning: !!isRunning,
    isConnecting,
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
