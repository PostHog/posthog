import { useHostTRPCClient } from "@posthog/host-router/react";
import type { Workspace } from "@posthog/shared";
import { useExternalAppAction } from "@posthog/ui/features/external-apps/useExternalAppAction";
import { useCallback } from "react";

export interface OpenFileContextMenuInput {
  absolutePath: string;
  filename: string;
  workspace: Workspace | null;
  mainRepoPath?: string;
  showCollapseAll?: boolean;
  onCollapseAll?: () => void;
}

export function useFileContextMenu() {
  const hostClient = useHostTRPCClient();
  const openExternalApp = useExternalAppAction();
  const openForFile = useCallback(
    async ({
      absolutePath,
      filename,
      workspace,
      mainRepoPath,
      showCollapseAll = false,
      onCollapseAll,
    }: OpenFileContextMenuInput) => {
      const result = await hostClient.contextMenu.showFileContextMenu.mutate({
        filePath: absolutePath,
        showCollapseAll,
      });
      if (!result.action) return;
      if (result.action.type === "collapse-all") {
        onCollapseAll?.();
      } else if (result.action.type === "external-app") {
        await openExternalApp(result.action.action, absolutePath, filename, {
          workspace,
          mainRepoPath,
        });
      }
    },
    [hostClient, openExternalApp],
  );
  return { openForFile };
}
