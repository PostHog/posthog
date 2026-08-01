export interface DeleteWorktreeParams {
  worktreePath: string;
  allTaskIds: string[];
  existingTaskIds: string[];
  folderPath: string;
}

export interface WorktreeMaintenanceDeps {
  confirmDeleteWorktree(params: {
    worktreePath: string;
    linkedTaskCount: number;
  }): Promise<{ confirmed: boolean }>;
  deleteWorkspace(params: {
    taskId: string;
    mainRepoPath: string;
  }): Promise<unknown>;
  deleteWorktree(params: {
    worktreePath: string;
    mainRepoPath: string;
  }): Promise<unknown>;
  deleteTask(taskId: string): Promise<unknown>;
  invalidate(folderPath: string): Promise<void>;
}

export async function deleteWorktree(
  deps: WorktreeMaintenanceDeps,
  params: DeleteWorktreeParams,
): Promise<{ deleted: boolean }> {
  const { worktreePath, allTaskIds, existingTaskIds, folderPath } = params;

  if (existingTaskIds.length > 0) {
    const { confirmed } = await deps.confirmDeleteWorktree({
      worktreePath,
      linkedTaskCount: existingTaskIds.length,
    });
    if (!confirmed) return { deleted: false };
  }

  if (allTaskIds.length > 0) {
    for (const taskId of allTaskIds) {
      await deps.deleteWorkspace({ taskId, mainRepoPath: folderPath });
    }
  } else {
    await deps.deleteWorktree({ worktreePath, mainRepoPath: folderPath });
  }

  for (const taskId of existingTaskIds) {
    await deps.deleteTask(taskId);
  }

  await deps.invalidate(folderPath);

  return { deleted: true };
}
