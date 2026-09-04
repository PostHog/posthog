import { CpuIcon, RobotIcon, UserIcon } from "@phosphor-icons/react";
import {
  describeReportOwner,
  reportWorkState,
  workStateLabel,
} from "@posthog/core/inbox/reportOwnership";
import type { SignalActorKind, SignalReport } from "@posthog/shared/types";
import { InboxBadge } from "@posthog/ui/features/inbox/components/utils/InboxBadge";
import type { ReactNode } from "react";

const OWNER_ICON: Record<SignalActorKind, typeof UserIcon> = {
  user: UserIcon,
  task: CpuIcon,
  agent: RobotIcon,
  system: CpuIcon,
};

/**
 * Who holds the report and how far the work has got. Renders nothing for an
 * unclaimed report, so rows keep their current shape until somebody claims one.
 */
export function ReportOwnerBadge({
  report,
}: {
  report: SignalReport;
}): ReactNode {
  const owner = describeReportOwner(report);
  if (!owner) return null;

  const state = reportWorkState(report);
  const Icon = OWNER_ICON[owner.kind];

  return (
    <InboxBadge
      variant={state === "working" ? "warning" : "default"}
      title={`${owner.detail} (${workStateLabel(state).toLowerCase()})`}
      className="max-w-40 gap-1"
    >
      <Icon size={11} className="shrink-0" />
      <span className="truncate">{owner.name}</span>
    </InboxBadge>
  );
}
