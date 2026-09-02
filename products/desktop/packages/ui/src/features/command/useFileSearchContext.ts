import { useFileSearchStore } from "@posthog/ui/features/command/fileSearchStore";
import { usePanelLayoutStore } from "@posthog/ui/features/panels/panelLayoutStore";
import { useCwd } from "@posthog/ui/features/sidebar/useCwd";
import { useAppView } from "@posthog/ui/router/useAppView";
import { useActiveRepoStore } from "@posthog/ui/shell/activeRepoStore";
import { useCallback } from "react";

export interface FileSearchContext {
  repoPath: string | undefined;
  recentFiles: string[];
  selectFile: (path: string) => void;
}

/**
 * Inside a task: the task's worktree, opening into its editor split. On the
 * new-task screen: the selected local repo (cloud "owner/repo" slugs excluded),
 * opening into the inline preview.
 */
export function useFileSearchContext(): FileSearchContext {
  const view = useAppView();
  const fileTaskId = view.type === "task-detail" ? view.taskId : undefined;

  const taskRepoPath = useCwd(fileTaskId ?? "");
  const selectedRepoPath = useActiveRepoStore((s) => s.path);
  const inputRepoPath =
    view.type === "task-input" && selectedRepoPath.startsWith("/")
      ? selectedRepoPath
      : undefined;
  const repoPath = taskRepoPath ?? inputRepoPath;

  const openFileInSplit = usePanelLayoutStore((s) => s.openFileInSplit);
  // In-task recents only (panelLayoutStore); the new-task screen has none.
  const taskRecentFiles = usePanelLayoutStore((s) =>
    fileTaskId ? s.taskLayouts[fileTaskId]?.recentFiles : undefined,
  );
  const recentFiles = taskRecentFiles ?? [];
  const openNewTaskFile = useFileSearchStore((s) => s.openPreview);

  const selectFile = useCallback(
    (path: string) => {
      if (fileTaskId) {
        openFileInSplit(fileTaskId, path, false);
      } else {
        openNewTaskFile(path);
      }
    },
    [fileTaskId, openFileInSplit, openNewTaskFile],
  );

  return { repoPath, recentFiles, selectFile };
}
