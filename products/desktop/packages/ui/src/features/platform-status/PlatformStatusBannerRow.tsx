import { WarningCircle } from "@phosphor-icons/react";
import { Button } from "@posthog/quill";

const STATUS_COPY = {
  degraded_performance: "PostHog Desktop is experiencing degraded performance.",
  partial_outage: "PostHog Desktop is experiencing an outage.",
  major_outage: "PostHog Desktop is experiencing an outage.",
} as const;

type PlatformStatusBannerRowProps = {
  status: keyof typeof STATUS_COPY;
  onOpenStatusPage: () => void;
};

export function PlatformStatusBannerRow({
  status,
  onOpenStatusPage,
}: PlatformStatusBannerRowProps): JSX.Element {
  return (
    <div className="no-drag shrink-0 px-2 pt-2 pb-1">
      <div className="flex w-full items-center gap-2.5 rounded-md border border-amber-7 bg-amber-3 px-3 py-2 text-amber-12 dark:border-amber-8 dark:bg-amber-4">
        <WarningCircle size={16} weight="duotone" className="shrink-0" />
        <span className="min-w-0 flex-1 font-medium text-[13px]">
          {STATUS_COPY[status]}
        </span>
        <Button
          variant="outline"
          size="sm"
          onClick={onOpenStatusPage}
          data-attr="desktop-platform-status-page"
        >
          View status
        </Button>
      </div>
    </div>
  );
}
