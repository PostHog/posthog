import { useHostTRPC } from "@posthog/host-router/react";
import { useMutationState } from "@tanstack/react-query";
import { useMemo } from "react";

export interface PendingTaskFiling {
  channelId: string;
  taskId: string;
  submittedAt: number;
}

function isTaskFilingVariables(
  value: unknown,
): value is Pick<PendingTaskFiling, "channelId" | "taskId"> {
  if (!value || typeof value !== "object") return false;
  return (
    "channelId" in value &&
    typeof value.channelId === "string" &&
    "taskId" in value &&
    typeof value.taskId === "string"
  );
}

export function latestPendingTaskFilings(
  filings: PendingTaskFiling[],
): Map<string, PendingTaskFiling> {
  const latestByTask = new Map<string, PendingTaskFiling>();
  for (const filing of filings) {
    latestByTask.set(filing.taskId, filing);
  }
  return latestByTask;
}

export function usePendingTaskFilings(): PendingTaskFiling[] {
  const trpc = useHostTRPC();
  const filings = useMutationState({
    filters: {
      mutationKey: trpc.channelTasks.file.mutationKey(),
      status: "pending",
    },
    select: (mutation): PendingTaskFiling | null => {
      const variables = mutation.state.variables;
      return isTaskFilingVariables(variables)
        ? { ...variables, submittedAt: mutation.state.submittedAt }
        : null;
    },
  });
  // useMutationState keeps one array while no filing changes, so memoize the
  // type guard to keep that identity. Callers list this array in useMemo
  // dependencies, and a fresh array each render would repeat the feed sort and
  // the sidebar item build on every unrelated render.
  return useMemo(
    () =>
      filings.filter((filing): filing is PendingTaskFiling => filing !== null),
    [filings],
  );
}
