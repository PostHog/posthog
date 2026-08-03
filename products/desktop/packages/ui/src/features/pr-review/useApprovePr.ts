import { useHostTRPC } from "@posthog/host-router/react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "../../primitives/toast";

export function useApprovePr(prUrl: string) {
  const trpc = useHostTRPC();
  const queryClient = useQueryClient();

  return useMutation({
    ...trpc.git.approvePr.mutationOptions(),
    onSuccess: async (result) => {
      if (!result.success) {
        toast.error(result.message || "Failed to approve pull request");
        return;
      }
      toast.success("Pull request approved");
      await queryClient.invalidateQueries(
        trpc.git.getPrReviewComments.queryFilter({ prUrl }),
      );
    },
    onError: (error) => {
      toast.error(error.message || "Failed to approve pull request");
    },
  });
}
