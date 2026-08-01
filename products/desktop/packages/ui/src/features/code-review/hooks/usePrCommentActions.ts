import { useService } from "@posthog/di/react";
import { useHostTRPC, useHostTRPCClient } from "@posthog/host-router/react";
import { useCallback } from "react";
import { toast } from "../../../primitives/toast";
import {
  IMPERATIVE_QUERY_CLIENT,
  type ImperativeQueryClient,
} from "../../../shell/queryClient";

export function usePrCommentActions(prUrl: string | null) {
  const trpc = useHostTRPC();
  const client = useHostTRPCClient();
  const queryClient = useService<ImperativeQueryClient>(
    IMPERATIVE_QUERY_CLIENT,
  );

  const reply = useCallback(
    async (commentId: number, body: string): Promise<boolean> => {
      if (!prUrl) return false;
      try {
        const result = await client.git.replyToPrComment.mutate({
          prUrl,
          commentId,
          body,
        });
        if (!result.success) {
          toast.error("Failed to post reply");
          return false;
        }
        await queryClient.invalidateQueries(
          trpc.git.getPrReviewComments.queryFilter({ prUrl }),
        );
        return true;
      } catch {
        toast.error("Failed to post reply");
        return false;
      }
    },
    [prUrl, client, trpc, queryClient],
  );

  const resolve = useCallback(
    async (threadNodeId: string, resolved: boolean): Promise<boolean> => {
      if (!prUrl) return false;
      const errorMessage = resolved
        ? "Failed to resolve thread"
        : "Failed to unresolve thread";
      try {
        const result = await client.git.resolveReviewThread.mutate({
          prUrl,
          threadNodeId,
          resolved,
        });
        if (!result.success) {
          toast.error(errorMessage);
          return false;
        }
        await queryClient.invalidateQueries(
          trpc.git.getPrReviewComments.queryFilter({ prUrl }),
        );
        return true;
      } catch {
        toast.error(errorMessage);
        return false;
      }
    },
    [prUrl, client, trpc, queryClient],
  );

  return { reply, resolve };
}
