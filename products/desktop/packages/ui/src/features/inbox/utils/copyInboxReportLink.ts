import { buildInboxDeeplink } from "@posthog/shared/deeplink";
import type { SignalReport } from "@posthog/shared/types";
import { toast } from "@posthog/ui/primitives/toast";

/**
 * Copy a deep link (`<scheme>://inbox/{reportId}`) for an inbox report to the
 * clipboard, toasting success or failure. Shared by every inbox detail surface
 * (reports, runs, pull requests) so the link format and copy feedback stay in
 * one place. The inbound side of these links lives in `useInboxDeepLink`.
 */
export function copyInboxReportLink(
  report: Pick<SignalReport, "id" | "title">,
): void {
  const url = buildInboxDeeplink(report.id, report.title, {
    isDevBuild: import.meta.env.DEV,
  });
  navigator.clipboard
    .writeText(url)
    .then(() => toast.success("Link copied"))
    .catch(() => toast.error("Couldn't copy link"));
}
