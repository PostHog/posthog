import { useHostTRPC } from "@posthog/host-router/react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "../../primitives/toast";

/** Reopen a closed (not merged) PR. */
export function useReopenPr(prUrl: string) {
  const trpc = useHostTRPC();
  const queryClient = useQueryClient();

  return useMutation({
    ...trpc.git.updatePrByUrl.mutationOptions(),
    onSuccess: async (result) => {
      if (!result.success) {
        toast.error(result.message || "Failed to reopen pull request");
        return;
      }
      toast.success("Pull request reopened");
      await Promise.all([
        queryClient.invalidateQueries(
          trpc.git.getPrInfoByUrl.queryFilter({ prUrl }),
        ),
        queryClient.invalidateQueries(
          trpc.git.getPrDetailsByUrl.queryFilter({ prUrl }),
        ),
      ]);
    },
    onError: (error) => {
      toast.error(error.message || "Failed to reopen pull request");
    },
  });
}
