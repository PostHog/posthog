import { useWorkspaceTRPC } from "@posthog/workspace-client/trpc";
import type { FileWatcherEvent } from "@posthog/workspace-client/types";
import { useSubscription } from "@trpc/tanstack-react-query";

export type { FileWatcherEvent };

export function useFileWatcher(
  repoPath: string | null,
  onEvent: (event: FileWatcherEvent) => void,
): void {
  const trpc = useWorkspaceTRPC();
  useSubscription(
    trpc.fileWatcher.watch.subscriptionOptions(
      { repoPath: repoPath ?? "" },
      { enabled: !!repoPath, onData: onEvent },
    ),
  );
}
