import { buildInboxDeeplink } from "@posthog/shared/deeplink";
import type { SignalReport } from "@posthog/shared/types";
import { toast } from "@posthog/ui/primitives/toast";
import { inboxReportUrl } from "@posthog/ui/utils/posthogLinks";

export type InboxReportLinkTarget = "web" | "desktop";

export async function copyInboxReportLink(
  report: Pick<SignalReport, "id" | "title">,
  target: InboxReportLinkTarget = "web",
): Promise<void> {
  const url =
    target === "desktop"
      ? buildInboxDeeplink(report.id, report.title, {
          isDevBuild: import.meta.env.DEV,
        })
      : inboxReportUrl(report.id);
  if (!url) {
    toast.error("Couldn't build a shareable link");
    return;
  }
  try {
    await navigator.clipboard.writeText(url);
    toast.success(
      target === "desktop" ? "Desktop link copied" : "Web link copied",
    );
  } catch {
    toast.error("Couldn't copy link");
  }
}
