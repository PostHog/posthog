import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
import {
  buildSuggestedReviewerFilterOptions,
  type SuggestedReviewerFilterOption,
} from "@posthog/ui/features/inbox/filterOptions";
import { useInboxAvailableSuggestedReviewers } from "@posthog/ui/features/inbox/hooks/useInboxReports";
import { useMemo } from "react";

interface InboxScopeOptions {
  people: SuggestedReviewerFilterOption[];
}

/**
 * People available in the inbox scope picker, the signed-in user first. That
 * user keeps a row of their own beside the pinned "For you" row: "For you" is
 * the default and resolves to whoever looks at it, so the named row is the only
 * way to pin the inbox to one person.
 */
export function useInboxScopeOptions(): InboxScopeOptions {
  const client = useOptionalAuthenticatedClient();
  const { data: currentUser } = useCurrentUser({ client });
  const { data: reviewersResponse } = useInboxAvailableSuggestedReviewers();

  const people = useMemo(
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

  return { people };
}
