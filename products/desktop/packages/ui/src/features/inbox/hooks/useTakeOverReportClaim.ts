import { reportKeys } from "@posthog/ui/features/inbox/hooks/useInboxReports";
import { useAuthenticatedMutation } from "@posthog/ui/hooks/useAuthenticatedMutation";
import { useQueryClient } from "@tanstack/react-query";

/** Take over the claim a teammate holds on a report, then refresh the lists that show who holds it. */
export function useTakeOverReportClaim() {
  const queryClient = useQueryClient();
  return useAuthenticatedMutation(
    (client, input: { reportId: string; claimId: string | null }) =>
      client.takeOverSignalReportClaim(input.reportId, input.claimId),
    {
      // Not awaited: the run that follows needs only the report id, and every
      // report list and chart refetching would hold it up.
      onSuccess: () => {
        void queryClient.invalidateQueries({
          queryKey: reportKeys.all,
          exact: false,
        });
      },
    },
  );
}
