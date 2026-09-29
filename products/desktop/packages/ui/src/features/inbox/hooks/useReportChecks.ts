import { inboxReportKeys } from "@posthog/core/inbox/inboxQuery";
import type {
  SignalReportCheck,
  SignalReportChecksResponse,
} from "@posthog/shared/types";
import { useAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { toast } from "@posthog/ui/primitives/toast";
import { useMutation, useQueryClient } from "@tanstack/react-query";

/**
 * A report's follow-up checks. Read once per mount rather than polled: a soak window is measured
 * in days and the coordinator's tick is coarse, so a poll would catch nothing.
 */
export function useReportChecks(reportId: string) {
  return useAuthenticatedQuery<SignalReportChecksResponse>(
    inboxReportKeys.checks(reportId),
    (client) => client.getSignalReportChecks(reportId),
    { enabled: !!reportId },
  );
}

/** Stop an open check. Terminal, so every caller confirms before it runs. */
export function useCancelReportCheck(reportId: string) {
  const client = useAuthenticatedClient();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (checkId: string) =>
      client.cancelSignalReportCheck(reportId, checkId),
    onSuccess: (cancelled: SignalReportCheck) => {
      // Patch the row in place: the list read is not polled, so a refetch is the only other
      // way the stopped check would stop reading as scheduled.
      queryClient.setQueryData<SignalReportChecksResponse>(
        inboxReportKeys.checks(reportId),
        (current) =>
          current && {
            ...current,
            results: current.results.map((check) =>
              check.id === cancelled.id ? cancelled : check,
            ),
          },
      );
    },
    onError: (error) => {
      toast.error(
        error instanceof Error ? error.message : "Couldn’t stop this check.",
      );
    },
  });
}
