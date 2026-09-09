import { ArrowLeftIcon } from "@phosphor-icons/react";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useReportPage } from "@posthog/ui/features/inbox/components/ReportPageContext";
import { useInboxTriageOrigin } from "@posthog/ui/features/inbox/hooks/useInboxBackTarget";
import { Link } from "@tanstack/react-router";

interface DetailBackLinkProps {
  to: string;
  label: string;
}

export function DetailBackLink({ to, label }: DetailBackLinkProps) {
  const triageOrigin = useInboxTriageOrigin();
  const report = useReportPage();
  const { channels } = useChannels({ enabled: report !== null });
  const channel = report?.channel_id
    ? channels.find((item) => item.id === report.channel_id)
    : undefined;
  if (report) {
    return (
      <>
        <span>Report</span>
        {channel && (
          <Link
            to="/spaces/$channelId"
            params={{ channelId: channel.id }}
            className="text-gray-11 hover:text-gray-12"
          >
            In #{channel.name}
          </Link>
        )}
      </>
    );
  }
  const returnsToTriage = to === "/inbox/reports" && triageOrigin !== null;

  return (
    <Link
      to={to}
      state={
        returnsToTriage
          ? (previous) => ({
              ...previous,
              inboxTriageOrigin: triageOrigin,
            })
          : undefined
      }
      className="inline-flex w-fit items-center gap-1.5 rounded-(--radius-1) text-[12.5px] text-gray-11 no-underline transition-colors hover:text-gray-12 focus-visible:text-gray-12 focus-visible:outline-(--gray-8) focus-visible:outline-2 focus-visible:outline-offset-2"
    >
      <ArrowLeftIcon size={14} />
      {returnsToTriage ? "Back to triage" : label}
    </Link>
  );
}
