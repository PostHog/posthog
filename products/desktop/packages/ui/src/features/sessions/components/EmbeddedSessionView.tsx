import type { Task } from "@posthog/shared/domain-types";
import { useEffect } from "react";
import { useDraftStore } from "../../message-editor/draftStore";
import { useSessionCallbacks } from "../hooks/useSessionCallbacks";
import { useSessionConnection } from "../hooks/useSessionConnection";
import { useSessionViewState } from "../hooks/useSessionViewState";
import { EmbeddedArtifactTabs } from "./EmbeddedArtifactTabs";
import { SessionView } from "./SessionView";

// A task's live session — the conversation thread plus the steering/queue
// composer — embedded in a compact container. Reuses the same
// state/connection/callback hooks as the full task view but drops the
// workspace-setup / provisioning chrome that doesn't apply when a session is
// shown inline. Shared by the command center and the canvas side panel.
export function EmbeddedSessionView({
  task,
  isActiveSession,
}: {
  task: Task;
  isActiveSession?: boolean;
}) {
  const taskId = task.id;
  const { requestFocus } = useDraftStore((s) => s.actions);

  const {
    session,
    repoPath,
    isCloud,
    isRunning,
    hasError,
    events,
    isPromptPending,
    promptStartedAt,
    isInitializing,
    cloudBranch,
    cloudStatus,
    errorTitle,
    errorMessage,
    errorRetryable,
  } = useSessionViewState(taskId, task);

  useSessionConnection({ taskId, task, session, repoPath, isCloud });

  const {
    handleSendPrompt,
    handleCancelPrompt,
    handleRetry,
    handleNewSession,
    handleBashCommand,
  } = useSessionCallbacks({ taskId, task, session, repoPath });

  useEffect(() => {
    requestFocus(taskId);
  }, [taskId, requestFocus]);

  return (
    <EmbeddedArtifactTabs taskId={taskId}>
      <SessionView
        events={events}
        taskId={taskId}
        task={task}
        isRunning={isRunning}
        isPromptPending={isPromptPending}
        promptStartedAt={promptStartedAt}
        onSendPrompt={handleSendPrompt}
        onBashCommand={isCloud ? undefined : handleBashCommand}
        onCancelPrompt={handleCancelPrompt}
        repoPath={repoPath}
        cloudBranch={cloudBranch}
        hasError={hasError}
        errorTitle={errorTitle}
        errorMessage={errorMessage ?? undefined}
        errorRetryable={errorRetryable}
        onRetry={handleRetry}
        onNewSession={isCloud ? undefined : handleNewSession}
        isInitializing={isInitializing}
        isCloud={isCloud}
        cloudStatus={cloudStatus}
        compact
        isActiveSession={isActiveSession}
      />
    </EmbeddedArtifactTabs>
  );
}
