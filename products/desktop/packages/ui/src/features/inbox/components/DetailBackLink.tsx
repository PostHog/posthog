import { ArrowLeftIcon } from "@phosphor-icons/react";
import { useInboxTriageOrigin } from "@posthog/ui/features/inbox/hooks/useInboxBackTarget";
import { Link } from "@tanstack/react-router";

interface DetailBackLinkProps {
  to: string;
  label: string;
}

export function DetailBackLink({ to, label }: DetailBackLinkProps) {
  const triageOrigin = useInboxTriageOrigin();
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
