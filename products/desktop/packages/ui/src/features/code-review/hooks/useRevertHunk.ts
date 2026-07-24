import type { FileDiffMetadata } from "@pierre/diffs";
import {
  type OptimisticRevertCallbacks,
  REVERT_HUNK_SERVICE,
  type RevertHunkService,
} from "@posthog/core/code-review/revertHunkService";
import { useService } from "@posthog/di/react";
import { useHostTRPC } from "@posthog/host-router/react";
import { useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

interface OptimisticRevertArgs {
  repoPath: string;
  filePath: string;
  hunkIndex: number;
  fileDiff: FileDiffMetadata;
}

export function useRevertHunk() {
  const service = useService<RevertHunkService>(REVERT_HUNK_SERVICE);
  const trpc = useHostTRPC();
  const queryClient = useQueryClient();

  return useCallback(
    async (
      args: OptimisticRevertArgs,
      callbacks: OptimisticRevertCallbacks,
    ) => {
      const reverted = await service.revertHunkOptimistic(args, callbacks);

      queryClient.invalidateQueries(
        trpc.git.getDiffHead.queryFilter({ directoryPath: args.repoPath }),
      );
      queryClient.invalidateQueries(
        trpc.git.getChangedFilesHead.queryFilter({
          directoryPath: args.repoPath,
        }),
      );

      return reverted;
    },
    [service, trpc, queryClient],
  );
}
