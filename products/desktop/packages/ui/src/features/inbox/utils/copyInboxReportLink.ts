import type { SignalReport } from "@posthog/shared/types";
import { toast } from "@posthog/ui/primitives/toast";
import { inboxReportUrl } from "@posthog/ui/utils/posthogLinks";

/**
 * Copy the report's browser-accessible PostHog URL. Shared by every inbox
 * detail surface so links still work when the recipient has no Desktop app.
 */
export async function copyInboxReportLink(
  report: Pick<SignalReport, "id">,
): Promise<void> {
  const url = inboxReportUrl(report.id);
  if (!url) {
    toast.error("Couldn't build a shareable link");
    return;
  }
  try {
    await navigator.clipboard.writeText(url);
    toast.success("Link copied");
  } catch {
    toast.error("Couldn't copy link");
  }
}
