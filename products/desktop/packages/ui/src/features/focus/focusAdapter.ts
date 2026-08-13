import { resolveService } from "@posthog/di/container";
import {
  HOST_TRPC_CLIENT,
  type HostTrpcClient,
} from "@posthog/host-router/client";
import type { FocusControllerDeps } from "./focusClient";

function host(): HostTrpcClient {
  return resolveService<HostTrpcClient>(HOST_TRPC_CLIENT);
}

export const focusDeps: FocusControllerDeps = {
  cancelSessionPrompt: async (sessionId, reason) => {
    await host().agent.cancelPrompt.mutate({ sessionId, reason });
  },
  checkout: (repoPath, branch) =>
    host().focus.checkout.mutate({ repoPath, branch }),
  cleanWorkingTree: (repoPath) =>
    host().focus.cleanWorkingTree.mutate({ repoPath }),
  deleteSession: (mainRepoPath) =>
    host().focus.deleteSession.mutate({ mainRepoPath }),
  detachWorktree: (worktreePath) =>
    host().focus.detachWorktree.mutate({ worktreePath }),
  getCommitSha: (repoPath) => host().focus.getCommitSha.query({ repoPath }),
  getCurrentBranch: async (mainRepoPath) =>
    await host().git.getCurrentBranch.query({
      directoryPath: mainRepoPath,
    }),
  getSession: (mainRepoPath) => host().focus.getSession.query({ mainRepoPath }),
  isDirty: (repoPath) => host().focus.isDirty.query({ repoPath }),
  listLocalTaskIds: async (mainRepoPath) =>
    (await host().workspace.getLocalTasks.query({ mainRepoPath })).map(
      ({ taskId }) => taskId,
    ),
  listSessionIds: async (taskId) =>
    (await host().agent.listSessions.query({ taskId })).map(
      ({ taskRunId }) => taskRunId,
    ),
  listWorktreeTaskIds: async (worktreePath) =>
    (await host().workspace.getWorktreeTasks.query({ worktreePath })).map(
      ({ taskId }) => taskId,
    ),
  notifySessionContext: (sessionId, context) =>
    host().agent.notifySessionContext.mutate({ sessionId, context }),
  reattachWorktree: (worktreePath, branch) =>
    host().focus.reattachWorktree.mutate({ worktreePath, branch }),
  saveSession: (session) => host().focus.saveSession.mutate(session),
  stash: (repoPath, message) =>
    host().focus.stash.mutate({ repoPath, message }),
  stashApply: (repoPath, stashRef) =>
    host().focus.stashApply.mutate({ repoPath, stashRef }),
  startSync: (mainRepoPath, worktreePath) =>
    host().focus.startSync.mutate({ mainRepoPath, worktreePath }),
  startWatchingMainRepo: (mainRepoPath) =>
    host().focus.startWatchingMainRepo.mutate({ mainRepoPath }),
  stopSync: () => host().focus.stopSync.mutate(),
  stopWatchingMainRepo: () => host().focus.stopWatchingMainRepo.mutate(),
  toRelativeWorktreePath: (absolutePath, mainRepoPath) =>
    host().focus.toRelativeWorktreePath.query({
      absolutePath,
      mainRepoPath,
    }),
  worktreeExistsAtPath: (relativePath) =>
    host().focus.worktreeExistsAtPath.query({ relativePath }),
};
