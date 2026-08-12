import { X } from "@phosphor-icons/react";
import type { Task } from "@posthog/shared/domain-types";
import {
  ArtifactTabHostProvider,
  type ArtifactTarget,
} from "@posthog/ui/features/panels/useOpenArtifact";
import { RevealPanelsProvider } from "@posthog/ui/features/panels/useRevealPanels";
import { openTask } from "@posthog/ui/router/useOpenTask";
import { useCallback, useEffect, useState } from "react";
import { useDraftStore } from "../../message-editor/draftStore";
import { useSessionCallbacks } from "../hooks/useSessionCallbacks";
import { useSessionConnection } from "../hooks/useSessionConnection";
import { useSessionViewState } from "../hooks/useSessionViewState";
import { ArtifactPreview } from "./ArtifactPreview";
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

  const [artifactTabs, setArtifactTabs] = useState<ArtifactTarget[]>([]);
  const [activeArtifactId, setActiveArtifactId] = useState<string | null>(null);

  const openArtifact = useCallback((artifact: ArtifactTarget) => {
    setArtifactTabs((tabs) =>
      tabs.some((tab) => tab.artifactId === artifact.artifactId)
        ? tabs
        : [...tabs, artifact],
    );
    setActiveArtifactId(artifact.artifactId);
  }, []);

  const closeArtifact = useCallback((artifactId: string) => {
    setArtifactTabs((tabs) =>
      tabs.filter((tab) => tab.artifactId !== artifactId),
    );
    setActiveArtifactId((active) => (active === artifactId ? null : active));
  }, []);

  // Source files and context open in the task's editor panels, which exist on
  // the task's own route, so opening one there takes the user with it.
  const revealPanels = useCallback(() => {
    void openTask(task);
  }, [task]);

  const activeArtifact =
    artifactTabs.find((tab) => tab.artifactId === activeArtifactId) ?? null;

  return (
    <RevealPanelsProvider reveal={revealPanels}>
      <ArtifactTabHostProvider open={openArtifact}>
        <div className="flex h-full min-h-0 flex-col">
          {artifactTabs.length > 0 && (
            <div className="flex shrink-0 items-center gap-1 overflow-hidden border-gray-6 border-b px-1 py-1">
              <EmbeddedTab
                label="Chat"
                active={!activeArtifact}
                onSelect={() => setActiveArtifactId(null)}
              />
              {artifactTabs.map((tab) => (
                <EmbeddedTab
                  key={tab.artifactId}
                  label={tab.name}
                  active={tab.artifactId === activeArtifact?.artifactId}
                  onSelect={() => setActiveArtifactId(tab.artifactId)}
                  onClose={() => closeArtifact(tab.artifactId)}
                />
              ))}
            </div>
          )}
          {/* An artifact covers the session rather than replacing it: the thread
              keeps its box, so its virtualized rows survive the round trip. */}
          <div className="relative flex min-h-0 flex-1 flex-col">
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
            {activeArtifact && (
              <div className="absolute inset-0 flex flex-col bg-background">
                <ArtifactPreview
                  taskId={taskId}
                  runId={activeArtifact.runId}
                  artifactId={activeArtifact.artifactId}
                  name={activeArtifact.name}
                />
              </div>
            )}
          </div>
        </div>
      </ArtifactTabHostProvider>
    </RevealPanelsProvider>
  );
}

function EmbeddedTab({
  label,
  active,
  onSelect,
  onClose,
}: {
  label: string;
  active: boolean;
  onSelect: () => void;
  onClose?: () => void;
}) {
  return (
    <div className="flex min-w-0 items-center">
      <button
        type="button"
        onClick={onSelect}
        title={label}
        className={`max-w-[160px] truncate rounded px-1.5 py-0.5 text-[12px] transition-colors ${
          active ? "bg-gray-4 text-gray-12" : "text-gray-10 hover:bg-gray-3"
        }`}
      >
        {label}
      </button>
      {onClose && (
        <button
          type="button"
          onClick={onClose}
          aria-label={`Close ${label}`}
          className="flex h-4 w-4 shrink-0 items-center justify-center rounded text-gray-10 transition-colors hover:bg-gray-4 hover:text-gray-12"
        >
          <X size={10} />
        </button>
      )}
    </div>
  );
}
