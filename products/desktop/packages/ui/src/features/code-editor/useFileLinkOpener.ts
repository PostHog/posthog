import type { FileHrefTarget } from "@posthog/core/code-editor/fileHref";
import { getRelativePath } from "@posthog/core/code-editor/pathUtils";
import type { FileOpenSource } from "@posthog/shared";
import { useMemo } from "react";
import { usePanelLayoutStore } from "../panels/panelLayoutStore";
import { useSessionTaskId } from "../sessions/useSessionTaskId";
import { useCwd } from "../sidebar/useCwd";
import { usePendingScrollStore } from "./pendingScrollStore";

/**
 * Opens a file an agent named, in the task's own worktree.
 *
 * Null when nothing would resolve: no task is in scope (a report, a GitHub
 * comment), or the task has no working directory because its workspace is gone
 * or suspended. Callers render plain text then — an affordance that opens a
 * panel which can only say "Failed to load file" costs the reader a click and
 * teaches them not to trust the next one.
 *
 * The stores are read through `getState`, not subscribed to: file chips and
 * links render many times per message, and none of them re-render on a panel
 * or scroll change.
 */
export function useFileLinkOpener(
  source: FileOpenSource,
): ((target: FileHrefTarget) => void) | null {
  const taskId = useSessionTaskId();
  const repoPath = useCwd(taskId ?? "");

  return useMemo(() => {
    if (!taskId || !repoPath) return null;
    return ({ path, line }: FileHrefTarget) => {
      const relativePath = getRelativePath(path, repoPath);
      if (line) {
        usePendingScrollStore
          .getState()
          .requestScroll(`${repoPath}/${relativePath}`, line);
      }
      usePanelLayoutStore
        .getState()
        .openFileInSplit(taskId, relativePath, true, source);
    };
  }, [taskId, repoPath, source]);
}
