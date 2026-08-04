import { resolveService } from "@posthog/di/container";
import {
  HOST_TRPC_CLIENT,
  type HostTrpcClient,
} from "@posthog/host-router/client";
import { cloneStore } from "@posthog/ui/features/clone/cloneStore";

/**
 * Start a clone operation. Registers it in the store and kicks off the host
 * clone. Progress and terminal status (complete/error) arrive via the
 * onCloneProgress subscription owned by CloneContribution, which also schedules
 * removal once the operation finishes — this action never owns timers.
 */
export function startClone(
  cloneId: string,
  repository: string,
  targetPath: string,
): void {
  cloneStore.getState().beginClone(cloneId, repository, targetPath);

  resolveService<HostTrpcClient>(HOST_TRPC_CLIENT)
    .git.cloneRepository.mutate({ repoUrl: repository, targetPath, cloneId })
    .catch((err: unknown) => {
      const message = err instanceof Error ? err.message : "Clone failed";
      cloneStore
        .getState()
        .applyProgress({ cloneId, status: "error", message });
    });
}
