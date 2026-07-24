import { useHostTRPC } from "@posthog/host-router/react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "../../primitives/toast";

export function useMergePr(prUrl: string) {
  const trpc = useHostTRPC();
  const queryClient = useQueryClient();

  return useMutation({
    ...trpc.git.mergePr.mutationOptions(),
    onSuccess: async (result) => {
      if (!result.success) {
        toast.error(result.message || "Failed to merge pull request");
        return;
      }
      toast.success("Pull request merged");
      // The PR's state (and everything derived from it) just changed.
      await Promise.all([
        queryClient.invalidateQueries(
          trpc.git.getPrInfoByUrl.queryFilter({ prUrl }),
        ),
        queryClient.invalidateQueries(
          trpc.git.getPrDetailsByUrl.queryFilter({ prUrl }),
        ),
        queryClient.invalidateQueries(
          trpc.git.getPrDiffStatsBatch.pathFilter(),
        ),
      ]);
    },
    onError: (error) => {
      toast.error(error.message || "Failed to merge pull request");
    },
  });
}
