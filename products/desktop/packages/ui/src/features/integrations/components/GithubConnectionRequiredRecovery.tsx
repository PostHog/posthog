import {
  describeGithubConnectError,
  GITHUB_CLOUD_TASK_CONNECTION_REQUIRED_MESSAGE,
  GITHUB_CONNECT_TIMEOUT_MESSAGE,
  GITHUB_CONNECTION_REQUIRED_MESSAGE,
  GITHUB_INSTALL_PENDING_MESSAGE,
  isGithubConnectionRequiredError,
} from "@posthog/core/integrations/connectErrors";
import {
  SESSION_SERVICE,
  type SessionService,
} from "@posthog/core/sessions/sessionService";
import { useService } from "@posthog/di/react";
import {
  buildLocalCodeSnapshotPrompt,
  getTaskRepository,
  normalizeRepoKey,
} from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { useFolders } from "@posthog/ui/features/folders/useFolders";
import { useIntegrationSelectors } from "@posthog/ui/features/integrations/store";
import { useGithubConnect } from "@posthog/ui/features/integrations/useGithubUserConnect";
import { useIntegrations } from "@posthog/ui/features/integrations/useIntegrations";
import { toast } from "@posthog/ui/primitives/toast";
import { openTaskInput } from "@posthog/ui/router/useOpenTask";
import { logger } from "@posthog/ui/shell/logger";
import { useHostCapabilities } from "@posthog/ui/shell/useHostCapabilities";
import {
  type ReactElement,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { GithubConnectionRequiredDialog } from "./GithubConnectionRequiredDialog";
import { GithubInstallRequestsBanner } from "./GithubInstallRequestsBanner";

interface GithubConnectionRequiredRecoveryProps {
  task: Task;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const log = logger.scope("github-connection-recovery");

function getRecoveryPrompt(task: Task): string {
  return (
    task.latest_run?.state.pending_user_message ??
    task.latest_run?.state.initial_prompt_override ??
    task.description
  );
}

function getRestartErrorMessage(error: unknown): string {
  const message =
    error instanceof Error
      ? error.message
      : "The task could not restart. Try again.";
  return isGithubConnectionRequiredError(message)
    ? "GitHub is connected, but it cannot access this repository. Update GitHub repository access, then try again."
    : message;
}

export function GithubConnectionRequiredRecovery({
  task,
  open,
  onOpenChange,
}: GithubConnectionRequiredRecoveryProps): ReactElement {
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  const cloudRegion = useAuthStateValue((state) => state.cloudRegion);
  const { localWorkspaces } = useHostCapabilities();
  const { folders } = useFolders();
  // The integration list alone answers this. `useRepositoryIntegration` would
  // also enumerate every repository of every installation, which this dialog
  // never reads.
  const { isPending: isLoadingIntegrations } = useIntegrations();
  const { hasGithubIntegration } = useIntegrationSelectors();
  const sessionService = useService<SessionService>(SESSION_SERVICE);
  const repository = getTaskRepository(task);
  const localFolder = useMemo(
    () =>
      repository
        ? folders.find(
            (folder) =>
              folder.remoteUrl &&
              normalizeRepoKey(folder.remoteUrl).toLowerCase() ===
                normalizeRepoKey(repository).toLowerCase(),
          )
        : undefined,
    [folders, repository],
  );

  const [restartError, setRestartError] = useState<string | null>(null);
  const [isRestarting, setIsRestarting] = useState(false);
  const [connectionReady, setConnectionReady] = useState(false);
  const pendingArtifactIds = task.latest_run?.state.pending_user_artifact_ids;
  const hasPendingArtifacts =
    Array.isArray(pendingArtifactIds) && pendingArtifactIds.length > 0;

  const retryInvestigation = useCallback(async () => {
    setIsRestarting(true);
    setRestartError(null);
    setConnectionReady(false);
    try {
      await sessionService.retryGithubRequiredCloudRun(
        task.id,
        getRecoveryPrompt(task),
      );
      onOpenChange(false);
    } catch (error) {
      // The service explains a refused resume, so keep its wording instead of
      // advice that cannot help, and leave the reason in the logs.
      const message = getRestartErrorMessage(error);
      log.error("Failed to restart a GitHub-blocked task", {
        taskId: task.id,
        error,
      });
      setRestartError(message);
      toast.error("The task could not restart", { description: message });
    } finally {
      setIsRestarting(false);
    }
  }, [onOpenChange, sessionService, task]);

  // The GitHub callback reaches every mounted recovery, not only the one that
  // started the flow, so a single connection would resume every blocked task
  // on screen. Retry the task whose dialog the user actually used.
  const connectStartedRef = useRef(false);

  const {
    error,
    isConnecting,
    isTimedOut,
    hasError,
    isPending,
    connect,
    reset,
  } = useGithubConnect({
    projectId,
    // Unknown until the list lands: an empty list reads as "no team
    // integration", which would send an admin through an org install they
    // do not need.
    projectHasTeamIntegration: isLoadingIntegrations
      ? null
      : hasGithubIntegration,
    onConnected: () => {
      if (!connectStartedRef.current) return;
      connectStartedRef.current = false;
      setConnectionReady(true);
    },
  });

  useEffect(() => {
    if (hasError || isTimedOut) connectStartedRef.current = false;
  }, [hasError, isTimedOut]);

  // The web host learns about OAuth only when its tab regains focus. It has no
  // deep-link callback, so release the loading state and let the user retry.
  useEffect(() => {
    if (localWorkspaces) return;
    const handleFocus = () => {
      if (!connectStartedRef.current) return;
      connectStartedRef.current = false;
      reset();
      setConnectionReady(true);
    };
    window.addEventListener("focus", handleFocus);
    return () => window.removeEventListener("focus", handleFocus);
  }, [localWorkspaces, reset]);

  // A task can carry several repositories, and the folder holds one of them.
  // The agent has to name the rest as unchecked rather than read as complete.
  const omittedRepositories = useMemo(
    () => (task.repositories ?? []).filter((entry) => entry !== repository),
    [repository, task.repositories],
  );

  const runLocally = useCallback(() => {
    if (!localFolder) return;
    onOpenChange(false);
    openTaskInput({
      folderId: localFolder.id,
      folderRepository: repository ?? undefined,
      folderRunEnvironment: "local",
      initialPrompt: buildLocalCodeSnapshotPrompt(
        getRecoveryPrompt(task),
        omittedRepositories,
      ),
      initialMode: "plan",
      reportAssociation: task.signal_report
        ? { reportId: task.signal_report, title: task.title }
        : undefined,
      channelId: task.channel ?? undefined,
    });
  }, [localFolder, omittedRepositories, onOpenChange, repository, task]);

  const connectionMessage =
    restartError ??
    (connectionReady
      ? "GitHub is connected. Retry the task to continue."
      : hasError
        ? describeGithubConnectError(error)
        : isTimedOut
          ? GITHUB_CONNECT_TIMEOUT_MESSAGE
          : isPending
            ? GITHUB_INSTALL_PENDING_MESSAGE
            : undefined);
  // Connecting and restarting both drive the dialog's primary button.
  const primaryActionBusy = isConnecting || isRestarting;

  const startConnect = useCallback(() => {
    if (projectId == null || cloudRegion == null) return;
    connectStartedRef.current = true;
    void connect();
  }, [cloudRegion, connect, projectId]);

  return (
    <GithubConnectionRequiredDialog
      open={open}
      isConnecting={primaryActionBusy}
      connectionMessage={connectionMessage}
      connectionReady={connectionReady && !restartError}
      requirementMessage={
        task.signal_report
          ? GITHUB_CONNECTION_REQUIRED_MESSAGE
          : GITHUB_CLOUD_TASK_CONNECTION_REQUIRED_MESSAGE
      }
      approvalPending={isPending}
      canConnect={!isLoadingIntegrations}
      installRequests={
        <GithubInstallRequestsBanner
          onFinishConnecting={startConnect}
          isConnecting={primaryActionBusy}
        />
      }
      canRunLocally={localWorkspaces && !!localFolder}
      recoveryWarning={
        hasPendingArtifacts
          ? "This restart does not include attachments from the failed task. Add them again after it starts."
          : undefined
      }
      onOpenChange={onOpenChange}
      onConnect={startConnect}
      onRetryTask={
        restartError || connectionReady
          ? () => void retryInvestigation()
          : undefined
      }
      onRunLocally={runLocally}
    />
  );
}
