import { inboxReportKeys } from "@posthog/core/inbox/inboxQuery";
import {
  buildPriorityFilterParam,
  buildSuggestedReviewerFilterParam,
} from "@posthog/core/inbox/reportFiltering";
import {
  INBOX_SCOPE_FOR_YOU,
  parseTeammateInboxScope,
} from "@posthog/core/inbox/reportMembership";
import type { SignalReportSectionCounts } from "@posthog/shared/types";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
import { useInboxReviewerScopeStore } from "@posthog/ui/features/inbox/stores/inboxReviewerScopeStore";
import { useInboxSignalsFilterStore } from "@posthog/ui/features/inbox/stores/inboxSignalsFilterStore";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";

export interface InboxSectionCounts {
  reviewAndMerge: number;
  needsPr: number;
  resolved: number;
  dismissed: number;
  isLoading: boolean;
}

/**
 * Server-side counts for the inbox's sections and badges.
 *
 * Loaded pages only contain a window of the inbox, so the counts come from the
 * backend, which applies each section's own status, actionability and PR
 * condition in one request.
 *
 * Scope and the priority filter are sent with the request so the counts move
 * with what the list shows. Search is a client-side title match, so surfaces
 * showing searched rows must count those rows instead.
 */
export function useInboxSectionCounts(): InboxSectionCounts {
  const scope = useInboxReviewerScopeStore((s) => s.scope);
  const priorityFilter = useInboxSignalsFilterStore((s) => s.priorityFilter);
  const client = useOptionalAuthenticatedClient();
  const { data: currentUser } = useCurrentUser({ client });

  const isForYou = scope === INBOX_SCOPE_FOR_YOU;
  const teammateUuid = parseTeammateInboxScope(scope);
  const reviewerUuid =
    teammateUuid ?? (isForYou ? (currentUser?.uuid ?? null) : null);
  const scopeReady = !isForYou || reviewerUuid != null;

  const params = {
    priority: buildPriorityFilterParam(priorityFilter),
    suggested_reviewers: reviewerUuid
      ? buildSuggestedReviewerFilterParam([reviewerUuid])
      : undefined,
  };
  const query = useAuthenticatedQuery<SignalReportSectionCounts>(
    inboxReportKeys.sectionCounts(params),
    (apiClient) => apiClient.getSignalReportSectionCounts(params),
    {
      enabled: scopeReady,
      refetchInterval: 60_000,
      refetchIntervalInBackground: false,
    },
  );

  return {
    reviewAndMerge: query.data?.review_and_merge ?? 0,
    needsPr: query.data?.needs_pr ?? 0,
    resolved: query.data?.resolved ?? 0,
    dismissed: query.data?.dismissed ?? 0,
    isLoading: query.isLoading || (isForYou && reviewerUuid == null),
  };
}
