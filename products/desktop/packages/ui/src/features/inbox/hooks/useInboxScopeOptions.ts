import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
import {
  buildSuggestedReviewerFilterOptions,
  type SuggestedReviewerFilterOption,
} from "@posthog/ui/features/inbox/filterOptions";
import { useInboxAvailableSuggestedReviewers } from "@posthog/ui/features/inbox/hooks/useInboxReports";
import { useMemo } from "react";

interface InboxScopeOptions {
  meOption: SuggestedReviewerFilterOption | null;
  teammateOptions: SuggestedReviewerFilterOption[];
}

/**
 * Available teammates for the inbox scope picker. The "For you" segment is
 * driven directly by the store; this hook only powers the dropdown attached
 * to the "Entire project" segment.
 */
export function useInboxScopeOptions(): InboxScopeOptions {
  const client = useOptionalAuthenticatedClient();
  const { data: currentUser } = useCurrentUser({ client });
  const { data: reviewersResponse } = useInboxAvailableSuggestedReviewers();

  const reviewerOptions = useMemo(
    () =>
      buildSuggestedReviewerFilterOptions(
        reviewersResponse?.results ?? [],
        currentUser
          ? {
              uuid: currentUser.uuid,
              email: currentUser.email,
              first_name: currentUser.first_name,
              last_name: currentUser.last_name,
            }
          : null,
      ),
    [currentUser, reviewersResponse?.results],
  );

  const meOption = reviewerOptions.find((option) => option.isMe) ?? null;
  const teammateOptions = reviewerOptions.filter((option) => !option.isMe);

  return { meOption, teammateOptions };
}
