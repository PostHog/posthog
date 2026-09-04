import { UserCircleIcon } from "@phosphor-icons/react";
import {
  describeReportOwner,
  reportWorkState,
  workStateLabel,
} from "@posthog/core/inbox/reportOwnership";
import { Button } from "@posthog/quill";
import type { SignalReport } from "@posthog/shared/types";
import { DetailSection } from "@posthog/ui/features/inbox/components/DetailSection";
import { ReportOwnerBadge } from "@posthog/ui/features/inbox/components/ReportOwnerBadge";
import { useReportClaim } from "@posthog/ui/features/inbox/hooks/useReportClaim";

/**
 * Who is working on the report, and the controls to take it on or hand it back.
 * An external agent can claim a report through the API, so the inbox has to
 * show that owner and let a person take the work back.
 */
export function ReportOwnerSection({ report }: { report: SignalReport }) {
  const { canRelease, mutation } = useReportClaim(report);
  const owner = describeReportOwner(report);
  const state = reportWorkState(report);

  if (!owner && state === "done") return null;

  return (
    <DetailSection Icon={UserCircleIcon} title="Working on it">
      <div className="flex min-w-0 flex-wrap items-center gap-3">
        {owner ? (
          <>
            <ReportOwnerBadge report={report} />
            <span className="min-w-0 flex-1 truncate text-[13px] text-gray-11">
              {owner.detail} · {workStateLabel(state)}
            </span>
          </>
        ) : (
          <span className="min-w-0 flex-1 text-[13px] text-gray-11">
            Nobody has claimed this report yet.
          </span>
        )}
        <span className="flex shrink-0 items-center gap-2">
          {canRelease && (
            <Button
              variant="outline"
              size="sm"
              disabled={mutation.isPending}
              onClick={() => mutation.mutate({ release: true })}
            >
              Release
            </Button>
          )}
          <Button
            variant="primary"
            size="sm"
            disabled={mutation.isPending}
            onClick={() => mutation.mutate({})}
          >
            {owner ? "Take over" : "Claim"}
          </Button>
        </span>
      </div>
    </DetailSection>
  );
}
