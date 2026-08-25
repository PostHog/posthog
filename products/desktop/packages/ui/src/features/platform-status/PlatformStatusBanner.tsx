import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { PlatformStatusBannerRow } from "./PlatformStatusBannerRow";
import { usePlatformStatus } from "./usePlatformStatus";

export function PlatformStatusBanner(): JSX.Element | null {
  const { status, statusPageUrl } = usePlatformStatus();
  const reportedStatus =
    status === "operational" || status === "unknown" ? null : status;
  if (!reportedStatus) {
    return null;
  }

  const openStatusPage = () => {
    openExternalUrl(statusPageUrl);
  };

  return (
    <PlatformStatusBannerRow
      status={reportedStatus}
      onOpenStatusPage={openStatusPage}
    />
  );
}
