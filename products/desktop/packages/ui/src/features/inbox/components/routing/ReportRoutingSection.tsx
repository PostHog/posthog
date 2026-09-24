import { CURRENT_OWNERSHIP_FLAG } from "@posthog/core/inbox/routing";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { ReportRoutingContent } from "./ReportRoutingContent";

export function ReportRoutingSection({ reportId }: { reportId: string }) {
  const enabled = useFeatureFlag(CURRENT_OWNERSHIP_FLAG);
  return enabled ? (
    <ReportRoutingContent key={reportId} reportId={reportId} />
  ) : null;
}
