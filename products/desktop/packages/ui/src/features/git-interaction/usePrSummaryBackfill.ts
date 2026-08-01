import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { taskKeys } from "../tasks/taskKeys";
import { backfillPrSummaries } from "./gitInteractionAdapter";

export function usePrSummaryBackfill(
  taskId: string,
  cloudUrls: string[],
  hasOtherPrs: boolean,
  summaries: Record<string, string>,
): void {
  const queryClient = useQueryClient();
  const summariesRef = useRef(summaries);
  summariesRef.current = summaries;
  const urlsKey = cloudUrls.join("\n");
  useEffect(() => {
    if (!hasOtherPrs || !urlsKey) return;
    void backfillPrSummaries(
      taskId,
      urlsKey.split("\n"),
      summariesRef.current,
    ).then((wrote) => {
      if (wrote) {
        void queryClient.invalidateQueries({ queryKey: taskKeys.lists() });
      }
    });
  }, [taskId, urlsKey, hasOtherPrs, queryClient]);
}
