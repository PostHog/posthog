import { resolveService } from "@posthog/di/container";
import {
  HOST_TRPC_CLIENT,
  type HostTrpcClient,
} from "@posthog/host-router/client";
import { expandTildePath, getTaskRepository } from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import type {
  EnsureWorkspaceResult,
  NavigationTaskBinder,
} from "@posthog/ui/features/navigation/taskBinder";
import { useProvisioningStore } from "@posthog/ui/features/provisioning/store";
import { WORKSPACE_QUERY_KEY } from "@posthog/ui/features/workspace/identifiers";
import { logger } from "@posthog/ui/shell/logger";
import {
  IMPERATIVE_QUERY_CLIENT,
  type ImperativeQueryClient,
} from "@posthog/ui/shell/queryClient";

const log = logger.scope("navigation-store");

function hostClient(): HostTrpcClient {
  return resolveService<HostTrpcClient>(HOST_TRPC_CLIENT);
}

function invalidateWorkspaces(): void {
  void resolveService<ImperativeQueryClient>(
    IMPERATIVE_QUERY_CLIENT,
  ).invalidateQueries({ queryKey: WORKSPACE_QUERY_KEY });
}

async function getTaskDirectory(
  taskId: string,
  repoKey?: string,
): Promise<string | null> {
  const workspaces = await hostClient().workspace.getAll.query();
  const workspace = workspaces?.[taskId] ?? null;
  if (workspace?.folderPath) {
    return expandTildePath(workspace.folderPath);
  }

  if (repoKey) {
    const repo = await hostClient().folders.getRepositoryByRemoteUrl.query({
      remoteUrl: repoKey,
    });
    if (repo) {
      return expandTildePath(repo.path);
    }
  }

  return null;
}

export const navigationTaskBinder: NavigationTaskBinder = {
  async ensureWorkspaceForTask(
    task: Task,
  ): Promise<EnsureWorkspaceResult | undefined> {
    const repoKey = getTaskRepository(task) ?? undefined;

    // A worktree task whose provisioning failed is kept with no workspace so
    // the user can retry. Don't auto-create a workspace here — that path only
    // makes a plain "local" checkout (below), silently downgrading the worktree.
    // The task view's retry prompt re-runs setup in worktree mode instead.
    if (useProvisioningStore.getState().errors[task.id]) {
      return undefined;
    }

    const workspaces = await hostClient().workspace.getAll.query();
    const existingWorkspace = workspaces?.[task.id] ?? null;

    // Repo-less channel task: its workspace is a synthetic scratch dir, not a
    // registered folder. Never register it (that would pop the "initialize git"
    // dialog on the empty scratch dir) or write a workspace row for it.
    if (existingWorkspace?.isScratch) {
      return undefined;
    }

    if (existingWorkspace?.folderId) {
      const folders = await hostClient().folders.getFolders.query();
      const folder = folders.find((f) => f.id === existingWorkspace.folderId);

      if (folder && folder.exists === false) {
        log.info("Folder path is stale, redirecting to folder settings", {
          folderId: folder.id,
          path: folder.path,
        });
        return { staleFolderId: folder.id };
      }

      if (folder) {
        return undefined;
      }
    }

    const directory = await getTaskDirectory(task.id, repoKey ?? undefined);

    if (directory) {
      const workspaceMode =
        task.latest_run?.environment === "cloud" ? "cloud" : "local";
      log.info("Ensuring workspace binding on task open", {
        taskId: task.id,
        directory,
        mode: workspaceMode,
        hadWorkspaceRecord: !!existingWorkspace,
        hasRun: !!task.latest_run?.id,
      });
      try {
        await hostClient().folders.addFolder.mutate({ folderPath: directory });

        await hostClient().workspace.create.mutate({
          taskId: task.id,
          mainRepoPath: directory,
          folderId: "",
          folderPath: directory,
          mode: workspaceMode,
        });
        invalidateWorkspaces();
      } catch (error) {
        log.error("Failed to auto-register folder on task open:", error);
      }
    } else if (task.latest_run?.environment === "cloud") {
      await hostClient().workspace.create.mutate({
        taskId: task.id,
        mainRepoPath: "",
        folderId: "",
        folderPath: "",
        mode: "cloud",
      });
      invalidateWorkspaces();
    } else {
      log.warn("No directory resolved on task open, workspace not created", {
        taskId: task.id,
        repoKey: repoKey ?? null,
        hasRun: !!task.latest_run?.id,
      });
    }

    return undefined;
  },
};
