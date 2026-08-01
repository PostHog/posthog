import { reportKeys } from "@posthog/ui/features/inbox/hooks/useInboxReports";
import { useAuthenticatedMutation } from "@posthog/ui/hooks/useAuthenticatedMutation";
import { toast } from "@posthog/ui/primitives/toast";
import { useQueryClient } from "@tanstack/react-query";

/** Thrown when the report is no longer archived by the time Restore runs. */
class ReportNoLongerArchivedError extends Error {
  constructor() {
    super("This report is no longer archived.");
    this.name = "ReportNoLongerArchivedError";
  }
}

/**
 * Restore an archived report back into the inbox. Reuses the `state` action's
 * `potential` transition (the same one the backend documents as "reopen"), which
 * is the only reopen path the backend exposes — the report re-enters the
 * pipeline as a fresh candidate rather than returning to its pre-archive
 * status (that prior status isn't persisted).
 *
 * Revalidates against the server before re-queueing: a Restore can be triggered
 * from a stale row (e.g. an Archive card left open while the report was restored
 * or progressed in another session), and `potential` is accepted for active
 * reports too — so restoring a no-longer-archived report would silently re-queue
 * it. If the fresh status isn't `suppressed`, no-op and refresh the lists instead.
 *
 * Invalidates `reportKeys.all` so both the Archive list and the pipeline
 * tabs refetch and the restored report moves between them.
 */
export function useInboxRestoreReport() {
  const queryClient = useQueryClient();

  return useAuthenticatedMutation(
    async (client, reportId: string) => {
      const current = await client.getSignalReport(reportId);
      if (current && current.status !== "suppressed") {
        throw new ReportNoLongerArchivedError();
      }
      return client.updateSignalReportState(reportId, { state: "potential" });
    },
    {
      onSuccess: async () => {
        await queryClient.invalidateQueries({
          queryKey: reportKeys.all,
          exact: false,
        });
        toast.success("Report restored to inbox");
      },
      onError: async (error) => {
        if (error instanceof ReportNoLongerArchivedError) {
          // The stale row's report already moved on — drop it from the list
          // rather than reporting a failure for an action that was moot.
          await queryClient.invalidateQueries({
            queryKey: reportKeys.all,
            exact: false,
          });
          toast.info(error.message);
          return;
        }
        toast.error(error.message || "Failed to restore report");
      },
    },
  );
}
