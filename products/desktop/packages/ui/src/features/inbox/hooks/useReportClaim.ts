import { SignalReportClaimConflictError } from "@posthog/api-client/posthog-client";
import { canReleaseReport } from "@posthog/core/inbox/reportOwnership";
import type { SignalReport } from "@posthog/shared/types";
import { reportKeys } from "@posthog/ui/features/inbox/hooks/useInboxReports";
import { useAuthenticatedMutation } from "@posthog/ui/hooks/useAuthenticatedMutation";
import { toast } from "@posthog/ui/primitives/toast";
import { useQueryClient } from "@tanstack/react-query";

interface ClaimInput {
  /** Attach or replace the report's pull request as part of the claim. */
  pr_url?: string;
  release?: boolean;
}

/**
 * Claim a report for the current user, release the current claim, or attach a
 * pull request to it. A claim conflict is recoverable: the report moved on, so
 * refetch and let the user see who owns it now instead of reporting a failure.
 */
export function useReportClaim(report: SignalReport) {
  const queryClient = useQueryClient();

  const mutation = useAuthenticatedMutation(
    (client, input: ClaimInput) => client.claimSignalReport(report.id, input),
    {
      onSuccess: async (updated, input) => {
        queryClient.setQueryData(reportKeys.detail(report.id), updated);
        await queryClient.invalidateQueries({
          queryKey: reportKeys.all,
          exact: false,
        });
        toast.success(input.release ? "Claim released" : "Report claimed");
      },
      onError: async (error) => {
        await queryClient.invalidateQueries({
          queryKey: reportKeys.all,
          exact: false,
        });
        if (error instanceof SignalReportClaimConflictError) {
          toast.info(`${error.message} Refreshed to show who owns it now.`);
          return;
        }
        toast.error(error.message || "Couldn’t update this report’s claim.");
      },
    },
  );

  return { canRelease: canReleaseReport(report), mutation };
}
