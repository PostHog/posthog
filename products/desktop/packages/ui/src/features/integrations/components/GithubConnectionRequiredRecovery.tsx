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
import { useCallback, useEffect, useMemo, useState } from "react";
import { GithubConnectionRequiredDialog } from "./GithubConnectionRequiredDialog";

interface GithubConnectionRequiredRecoveryProps {
  task: Task;
  required: boolean;
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
  required,
}: GithubConnectionRequiredRecoveryProps) {
  const [open, setOpen] = useState(required);
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
      setOpen(false);
    } catch {
      toast.error("GitHub connected, but the task could not restart", {
        description: "Open the task again and retry.",
      });
    }
  }, [sessionService, task]);

  const { error, isConnecting, isTimedOut, hasError, isPending, connect } =
    useGithubConnect({
      projectId,
      projectHasTeamIntegration: hasGithubIntegration,
      onConnected: () => void retryInvestigation(),
    });

  useEffect(() => {
    if (required) setOpen(true);
  }, [required]);

  const runLocally = useCallback(() => {
    if (!localFolder) return;
    setOpen(false);
    openTaskInput({
      folderId: localFolder.id,
      folderRepository: repository ?? undefined,
      folderRunEnvironment: "local",
      initialPrompt: buildLocalCodeSnapshotPrompt(getRecoveryPrompt(task)),
      initialMode: task.latest_run?.state.initial_permission_mode ?? "auto",
      reportAssociation: task.signal_report
        ? { reportId: task.signal_report, title: task.title }
        : undefined,
      channelId: task.channel ?? undefined,
    });
  }, [localFolder, repository, task]);

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
      onOpenChange={setOpen}
      onConnect={() => {
        if (projectId == null || cloudRegion == null) return;
        void connect();
      }}
      onRunLocally={runLocally}
    />
  );
}
