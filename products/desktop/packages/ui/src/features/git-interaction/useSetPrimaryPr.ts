import { useHostTRPC } from "@posthog/host-router/react";
import {
  buildPrOutput,
  promotePrUrl,
  readPrSummaries,
  readPrUrls,
} from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "../../primitives/toast";
import { sessionStoreSetters, useSessionStore } from "../sessions/sessionStore";
import { taskKeys } from "../tasks/taskKeys";
import { promoteTaskPrUrl } from "./gitInteractionAdapter";

function promoteOutput(
  output: Record<string, unknown> | null | undefined,
  prUrl: string,
): Record<string, unknown> {
  return buildPrOutput(
    output,
    promotePrUrl(readPrUrls(output), prUrl),
    readPrSummaries(output),
  );
}

export function useSetPrimaryPr(taskId: string) {
  const queryClient = useQueryClient();
  const trpc = useHostTRPC();
  return useMutation({
    mutationFn: (prUrl: string) => promoteTaskPrUrl(taskId, prUrl),
    onMutate: async (prUrl) => {
      const cachedKey = trpc.workspace.getCachedPrUrl.queryKey({ taskId });
      await Promise.all([
        queryClient.cancelQueries({ queryKey: taskKeys.lists() }),
        queryClient.cancelQueries({ queryKey: cachedKey }),
      ]);

      const previousLists = queryClient.getQueriesData<Task[]>({
        queryKey: taskKeys.lists(),
      });
      queryClient.setQueriesData<Task[]>(
        { queryKey: taskKeys.lists() },
        (tasks) =>
          tasks?.map((task) =>
            task.id === taskId && task.latest_run
              ? {
                  ...task,
                  latest_run: {
                    ...task.latest_run,
                    output: promoteOutput(task.latest_run.output, prUrl),
                  },
                }
              : task,
          ),
      );

      const previousCached = queryClient.getQueryData(cachedKey);
      queryClient.setQueryData(cachedKey, (prev) =>
        prev
          ? { ...prev, prUrl, prUrls: promotePrUrl(prev.prUrls, prUrl) }
          : prev,
      );

      const state = useSessionStore.getState();
      const taskRunId = state.taskIdIndex[taskId];
      const previousOutput = taskRunId
        ? state.sessions[taskRunId]?.cloudOutput
        : undefined;
      if (taskRunId && previousOutput) {
        sessionStoreSetters.updateCloudStatus(taskRunId, {
          output: promoteOutput(previousOutput, prUrl),
        });
      }

      return { previousLists, previousCached, taskRunId, previousOutput };
    },
    onError: (_err, _prUrl, context) => {
      for (const [key, data] of context?.previousLists ?? []) {
        queryClient.setQueryData(key, data);
      }
      if (context) {
        queryClient.setQueryData(
          trpc.workspace.getCachedPrUrl.queryKey({ taskId }),
          context.previousCached,
        );
        if (context.taskRunId && context.previousOutput) {
          sessionStoreSetters.updateCloudStatus(context.taskRunId, {
            output: context.previousOutput,
          });
        }
      }
      toast.error("Couldn't change primary PR");
    },
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: taskKeys.lists() }),
  });
}
