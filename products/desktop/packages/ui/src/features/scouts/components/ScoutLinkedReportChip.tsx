import { TrayIcon } from "@phosphor-icons/react";
import type { LinkedSignalReport } from "@posthog/api-client/posthog-client";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import { useOpenInboxReport } from "@posthog/ui/features/inbox/hooks/useOpenInboxReport";
import { track } from "@posthog/ui/shell/analytics";
import { Text } from "@radix-ui/themes";
import { useState } from "react";

/**
 * Footer chip on a scout emission card linking to the inbox report this finding
 * grouped into. Best effort: only rendered when the reverse lookup resolved a
 * report. Clicking opens the report in the inbox via the shared open-report
 * flow (fetch by id, seed cache, navigate to the right tab).
 */
export function ScoutLinkedReportChip({
  report,
  skillName,
}: {
  report: LinkedSignalReport;
  /** The emitting scout, attached to analytics when known. */
  skillName?: string;
}) {
  const openReport = useOpenInboxReport();
  const [opening, setOpening] = useState(false);

  return (
    <button
      type="button"
      disabled={opening}
      onClick={async () => {
        track(ANALYTICS_EVENTS.SCOUT_ACTION, {
          action_type: "open_linked_report",
          surface: "scout_detail",
          skill_name: skillName,
          report_status: report.status,
        });
        setOpening(true);
        try {
          await openReport(report.id);
        } finally {
          setOpening(false);
        }
      }}
      className="flex max-w-[16rem] items-center gap-1 rounded-full bg-(--iris-3) px-2 py-0.5 text-(--iris-11) transition-colors hover:bg-(--iris-4) disabled:opacity-60"
      title={report.title ?? "View linked report"}
    >
      <TrayIcon size={12} className="shrink-0" />
      <Text className="truncate text-[11px]">
        {report.title ? `In report: ${report.title}` : "View linked report"}
      </Text>
    </button>
  );
}
