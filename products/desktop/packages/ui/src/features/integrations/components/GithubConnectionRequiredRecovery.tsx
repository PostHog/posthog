import {
  describeGithubConnectError,
  GITHUB_CLOUD_TASK_CONNECTION_REQUIRED_MESSAGE,
  GITHUB_CONNECT_TIMEOUT_MESSAGE,
  GITHUB_CONNECTION_REQUIRED_MESSAGE,
  GITHUB_INSTALL_PENDING_MESSAGE,
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
import { useGithubConnect } from "@posthog/ui/features/integrations/useGithubUserConnect";
import { useRepositoryIntegration } from "@posthog/ui/features/integrations/useIntegrations";
import { toast } from "@posthog/ui/primitives/toast";
import { openTaskInput } from "@posthog/ui/router/useOpenTask";
import { useHostCapabilities } from "@posthog/ui/shell/useHostCapabilities";
import {
  type ReactElement,
  useCallback,
  useEffect,
  useMemo,
  useRef,
} from "react";
import { GithubConnectionRequiredDialog } from "./GithubConnectionRequiredDialog";

interface GithubConnectionRequiredRecoveryProps {
  task: Task;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

function getRecoveryPrompt(task: Task): string {
  return (
    task.latest_run?.state.pending_user_message ??
    task.latest_run?.state.initial_prompt_override ??
    task.description
  );
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
  const { hasGithubIntegration } = useRepositoryIntegration();
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

  const retryInvestigation = useCallback(async () => {
    try {
      await sessionService.retryGithubRequiredCloudRun(
        task.id,
        getRecoveryPrompt(task),
      );
      onOpenChange(false);
    } catch {
      toast.error("GitHub connected, but the task could not restart", {
        description: "Open the task again and retry.",
      });
    }
  }, [onOpenChange, sessionService, task]);

  // The GitHub callback reaches every mounted recovery, not only the one that
  // started the flow, so a single connection would resume every blocked task
  // on screen. Retry the task whose dialog the user actually used.
  const connectStartedRef = useRef(false);

  const { error, isConnecting, isTimedOut, hasError, isPending, connect } =
    useGithubConnect({
      projectId,
      projectHasTeamIntegration: hasGithubIntegration,
      onConnected: () => {
        if (!connectStartedRef.current) return;
        connectStartedRef.current = false;
        void retryInvestigation();
      },
    });

  useEffect(() => {
    if (hasError || isTimedOut) connectStartedRef.current = false;
  }, [hasError, isTimedOut]);

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

  const connectionMessage = hasError
    ? describeGithubConnectError(error)
    : isTimedOut
      ? GITHUB_CONNECT_TIMEOUT_MESSAGE
      : isPending
        ? GITHUB_INSTALL_PENDING_MESSAGE
        : undefined;

  return (
    <GithubConnectionRequiredDialog
      open={open}
      isConnecting={isConnecting}
      connectionMessage={connectionMessage}
      requirementMessage={
        task.signal_report
          ? GITHUB_CONNECTION_REQUIRED_MESSAGE
          : GITHUB_CLOUD_TASK_CONNECTION_REQUIRED_MESSAGE
      }
      approvalPending={isPending}
      canRunLocally={localWorkspaces && !!localFolder}
      onOpenChange={onOpenChange}
      onConnect={() => {
        if (projectId == null || cloudRegion == null) return;
        connectStartedRef.current = true;
        void connect();
      }}
      onRunLocally={runLocally}
    />
  );
}
