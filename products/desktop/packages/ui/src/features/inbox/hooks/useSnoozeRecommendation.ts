import { buildDetailActionEvent } from "@posthog/core/inbox/reportActionEvents";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import type { SignalReport } from "@posthog/shared/types";
import { reportKeys } from "@posthog/ui/features/inbox/hooks/useInboxReports";
import { useAuthenticatedMutation } from "@posthog/ui/hooks/useAuthenticatedMutation";
import { toast } from "@posthog/ui/primitives/toast";
import { track } from "@posthog/ui/shell/analytics";
import { useQueryClient } from "@tanstack/react-query";

export function useSnoozeRecommendation() {
  const queryClient = useQueryClient();
  return useAuthenticatedMutation(
    (client, { report, snoozed }: { report: SignalReport; snoozed: boolean }) =>
      client.snoozeSignalReport(report.id, snoozed),
    {
      onSuccess: async (_, { report, snoozed }) => {
        track(ANALYTICS_EVENTS.INBOX_REPORT_ACTION, {
          ...buildDetailActionEvent(report, snoozed ? "snooze" : "undo_snooze"),
          surface: "shortlist",
          rank: -1,
          list_size: 0,
          priority: report.priority ?? null,
          actionability: report.actionability ?? null,
        });
        await queryClient.invalidateQueries({ queryKey: reportKeys.all });
      },
      onError: () => toast.error("Could not change your shortlist. Try again."),
    },
  );
}
