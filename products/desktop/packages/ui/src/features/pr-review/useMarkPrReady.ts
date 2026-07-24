import { useHostTRPC } from "@posthog/host-router/react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "../../primitives/toast";

/** Flip a draft PR to "ready for review". */
export function useMarkPrReady(prUrl: string) {
  const trpc = useHostTRPC();
  const queryClient = useQueryClient();

  return useMutation({
    ...trpc.git.updatePrByUrl.mutationOptions(),
    onSuccess: async (result) => {
      if (!result.success) {
        toast.error(result.message || "Failed to mark as ready for review");
        return;
      }
      toast.success("Marked as ready for review");
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
      toast.error(error.message || "Failed to mark as ready for review");
    },
  });
}
