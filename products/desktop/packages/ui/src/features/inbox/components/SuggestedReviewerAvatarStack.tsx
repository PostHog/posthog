import {
  extractSuggestedReviewers,
  suggestedReviewerDisplayName,
} from "@posthog/core/inbox/artefacts";
import type { SignalReportArtefactsResponse } from "@posthog/shared/types";
import { SuggestedReviewerAvatar } from "@posthog/ui/features/inbox/components/utils/SuggestedReviewerAvatar";
import { useInboxReportArtefacts } from "@posthog/ui/features/inbox/hooks/useInboxReports";
import { Flex, Tooltip } from "@radix-ui/themes";

const MAX_VISIBLE = 4;

interface SuggestedReviewerAvatarStackProps {
  reportId: string;
  artefacts?: SignalReportArtefactsResponse | null;
}

export function SuggestedReviewerAvatarStack({
  reportId,
  artefacts,
}: SuggestedReviewerAvatarStackProps) {
  const { data } = useInboxReportArtefacts(reportId, {
    enabled: artefacts === undefined,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });
  const reviewers = extractSuggestedReviewers(
    artefacts?.results ?? data?.results,
  ).filter((reviewer) => reviewer.github_login);
  if (reviewers.length === 0) {
    return null;
  }

  const visible = reviewers.slice(0, MAX_VISIBLE);
  const overflow = reviewers.length - visible.length;

  return (
    <Flex
      align="center"
      className="shrink-0"
      aria-label={`${reviewers.length} suggested reviewer${reviewers.length === 1 ? "" : "s"}`}
    >
      <Flex align="center" className="-space-x-1.5">
        {visible.map((reviewer) => {
          const name = suggestedReviewerDisplayName(reviewer);
          return (
            <Tooltip key={reviewer.github_login} content={name}>
              <SuggestedReviewerAvatar
                githubLogin={reviewer.github_login}
                size="sm"
                className="ring-(--color-panel-solid) ring-2"
              />
            </Tooltip>
          );
        })}
        {overflow > 0 ? (
          <span className="inline-flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-(--gray-3) px-1 font-semibold text-[9px] text-gray-11 leading-none ring-(--color-panel-solid) ring-2">
            +{overflow}
          </span>
        ) : null}
      </Flex>
    </Flex>
  );
}
