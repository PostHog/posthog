import {
  displayConventionalCommitTitle,
  parseConventionalCommitTitle,
} from "@posthog/core/inbox/reportPresentation";
import { ConventionalCommitScopeTag } from "@posthog/ui/features/inbox/components/ConventionalCommitScopeTag";
import { DetailBackLink } from "@posthog/ui/features/inbox/components/DetailBackLink";
import { InboxMetaRow } from "@posthog/ui/features/inbox/components/InboxMetaRow";
import { Flex, Text } from "@radix-ui/themes";
import type { ReactNode } from "react";

interface InboxDetailPageHeaderProps {
  backTo: string;
  backLabel: string;
  breadcrumb?: ReactNode;
  reportTitle: string | null | undefined;
  fallbackTitle: string;
  /** Compact badges (priority / status / for-you / actionability). Joins the meta row. */
  badges?: ReactNode;
  /** Inline meta items (timestamp, findings count, source). */
  meta?: ReactNode;
  /** Action button cluster (dismiss, discuss, primary). */
  actions?: ReactNode;
}

/**
 * Compact detail-page header used by all three inbox detail screens.
 *
 *   ┌──────────────────────────────────────────────────────────────────────┐
 *   │ ← Back / breadcrumb                                                  │
 *   │ [scope] Title                                                        │
 *   │ ───────────────────────────────────────────────────────────────────  │
 *   │ [badges][meta]                              [Dismiss][Discuss][Open] │
 *   └──────────────────────────────────────────────────────────────────────┘
 *
 * Everything secondary lives on the single bottom row – badges (priority,
 * status, for-you) flow into the meta items (timestamp, findings count,
 * source) on the left; action buttons stay right-aligned. This collapses
 * the previous three rows (badges → meta → actions) into one and recovers
 * a lot of vertical space.
 */
export function InboxDetailPageHeader({
  backTo,
  backLabel,
  breadcrumb,
  reportTitle,
  fallbackTitle,
  badges,
  meta,
  actions,
}: InboxDetailPageHeaderProps) {
  const conventionalTitle = parseConventionalCommitTitle(reportTitle);
  const displayTitle = displayConventionalCommitTitle(
    reportTitle,
    fallbackTitle,
  );
  const hasBottomRow = !!badges || !!meta || !!actions;

  return (
    <Flex
      direction="column"
      gap="3"
      className="shrink-0 border-(--gray-5) border-b px-6 pt-5 pb-4"
    >
      <Flex align="center" gap="2" className="text-[12.5px] text-gray-11">
        <DetailBackLink to={backTo} label={backLabel} />
        {breadcrumb}
      </Flex>

      <Flex align="center" gap="2" wrap="wrap" className="min-w-0">
        {conventionalTitle && (
          <ConventionalCommitScopeTag
            type={conventionalTitle.type}
            scope={conventionalTitle.scope}
            compact
          />
        )}
        <Text className="min-w-0 font-bold text-[24px] text-gray-12 leading-tight tracking-tight">
          {displayTitle}
        </Text>
      </Flex>

      {hasBottomRow && (
        <Flex align="center" justify="between" gap="3" wrap="wrap">
          <Flex
            align="center"
            gap="2"
            wrap="wrap"
            className="min-w-0 flex-1 text-[12px] text-gray-11"
          >
            {badges}
            {badges && meta && (
              <span className="text-(--gray-7)" aria-hidden>
                ·
              </span>
            )}
            {meta && <InboxMetaRow>{meta}</InboxMetaRow>}
          </Flex>
          {actions && (
            <Flex align="center" gap="2" className="shrink-0">
              {actions}
            </Flex>
          )}
        </Flex>
      )}
    </Flex>
  );
}
