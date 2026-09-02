import { CheckIcon, MagnifyingGlassIcon } from "@phosphor-icons/react";
import { toSuggestedReviewerWriteContent } from "@posthog/core/inbox/artefacts";
import { selectSuggestedReviewersArtefact } from "@posthog/core/inbox/reportArtefacts";
import { Button, Spinner } from "@posthog/quill";
import type { InboxReportActionSurface } from "@posthog/shared/analytics-events";
import type {
  AvailableSuggestedReviewer,
  SignalReport,
  SuggestedReviewer,
} from "@posthog/shared/types";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
import { SuggestedReviewerAvatar } from "@posthog/ui/features/inbox/components/utils/SuggestedReviewerAvatar";
import {
  buildSuggestedReviewerFilterOptions,
  getSuggestedReviewerDisplayName,
} from "@posthog/ui/features/inbox/filterOptions";
import {
  useInboxAvailableSuggestedReviewers,
  useInboxReportArtefacts,
  useUpdateSuggestedReviewers,
} from "@posthog/ui/features/inbox/hooks/useInboxReports";
import {
  useReportActionResultTracker,
  useReportActionTracker,
} from "@posthog/ui/features/inbox/hooks/useReportActionTracker";
import { useDeferredValue, useMemo, useState } from "react";

function reviewerMatchesAvailable(
  reviewer: SuggestedReviewer,
  available: AvailableSuggestedReviewer,
): boolean {
  if (reviewer.user?.uuid && reviewer.user.uuid === available.uuid) return true;
  return (
    !!reviewer.github_login &&
    !!available.github_login &&
    reviewer.github_login.toLowerCase() === available.github_login.toLowerCase()
  );
}

export function ReviewerSearchList({
  report,
  surface,
  enabled = true,
}: {
  report: SignalReport;
  surface: InboxReportActionSurface;
  enabled?: boolean;
}): React.JSX.Element {
  const client = useOptionalAuthenticatedClient();
  const fireAction = useReportActionTracker(report, surface);
  const trackResult = useReportActionResultTracker(report, surface);
  const { data: currentUser } = useCurrentUser({ client, enabled: !!client });
  const {
    data,
    isLoading: artefactsLoading,
    isError: artefactsError,
    refetch: refetchArtefacts,
  } = useInboxReportArtefacts(report.id, { enabled });
  const artefact = selectSuggestedReviewersArtefact(data?.results ?? []);
  const reviewers = useMemo(() => artefact?.content ?? [], [artefact]);
  const [query, setQuery] = useState("");
  const deferredQuery = useDeferredValue(query);
  const { mutate: updateReviewers, isPending } = useUpdateSuggestedReviewers(
    report.id,
  );
  const {
    data: availableReviewers,
    isFetching,
    isError: availableReviewersError,
    refetch: refetchAvailableReviewers,
  } = useInboxAvailableSuggestedReviewers({
    enabled: !!client && enabled,
    query: deferredQuery,
  });
  const options = useMemo(() => {
    const built = buildSuggestedReviewerFilterOptions(
      availableReviewers?.results ?? [],
      currentUser,
    );
    const normalizedQuery = deferredQuery.trim().toLowerCase();
    if (!normalizedQuery) return built;
    return built.filter(
      (option) =>
        option.name.toLowerCase().includes(normalizedQuery) ||
        option.email.toLowerCase().includes(normalizedQuery) ||
        option.github_login.toLowerCase().includes(normalizedQuery),
    );
  }, [availableReviewers?.results, currentUser, deferredQuery]);

  const toggleReviewer = (option: AvailableSuggestedReviewer): void => {
    const existing = reviewers.find((reviewer) =>
      reviewerMatchesAvailable(reviewer, option),
    );
    if (existing) {
      const next = reviewers.filter((reviewer) => reviewer !== existing);
      fireAction("remove_suggested_reviewer", {
        suggested_reviewer_login: existing.github_login || undefined,
        suggested_reviewer_uuid: existing.user?.uuid,
      });
      const startedAt = Date.now();
      updateReviewers(
        {
          content: toSuggestedReviewerWriteContent(next),
          optimisticReviewers: next,
        },
        {
          onSuccess: () =>
            trackResult("remove_suggested_reviewer", "succeeded", startedAt),
          onError: () =>
            trackResult(
              "remove_suggested_reviewer",
              "failed",
              startedAt,
              "request_failed",
            ),
        },
      );
      return;
    }

    const optimisticEntry: SuggestedReviewer = {
      github_login: option.github_login,
      github_name: option.name || null,
      relevant_commits: [],
      user: {
        id: 0,
        uuid: option.uuid,
        email: option.email,
        first_name: option.name,
        last_name: "",
      },
    };
    fireAction("add_suggested_reviewer", {
      suggested_reviewer_login: option.github_login || undefined,
      suggested_reviewer_uuid: option.uuid,
    });
    const startedAt = Date.now();
    updateReviewers(
      {
        content: [
          ...toSuggestedReviewerWriteContent(reviewers),
          { user_uuid: option.uuid },
        ],
        optimisticReviewers: [...reviewers, optimisticEntry],
      },
      {
        onSuccess: () =>
          trackResult("add_suggested_reviewer", "succeeded", startedAt),
        onError: () =>
          trackResult(
            "add_suggested_reviewer",
            "failed",
            startedAt,
            "request_failed",
          ),
      },
    );
  };

  const failedWithoutData =
    (artefactsError && !data) ||
    (availableReviewersError && !availableReviewers);

  return (
    // Keep typing in the search field out of the parent menu's typeahead handler.
    // biome-ignore lint/a11y/noStaticElementInteractions: keyboard fencing only
    <div
      className="flex w-72 flex-col gap-2 p-2"
      onKeyDown={(event) => {
        if (event.key !== "Escape") event.stopPropagation();
      }}
    >
      <div className="flex items-center gap-2 rounded-(--radius-2) border border-(--gray-6) bg-(--color-background) px-2 py-1">
        <MagnifyingGlassIcon size={12} className="shrink-0 text-gray-10" />
        <input
          type="search"
          aria-label="Search users"
          // biome-ignore lint/a11y/noAutofocus: opening the submenu is an explicit search action
          autoFocus
          placeholder="Search users…"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          className="min-w-0 flex-1 bg-transparent text-[13px] text-gray-12 outline-none placeholder:text-(--gray-9)"
        />
      </div>
      <div className="max-h-[280px] overflow-y-auto">
        {artefactsLoading ||
        (isFetching && !availableReviewers?.results.length) ? (
          <div className="flex items-center justify-center py-3">
            <Spinner />
          </div>
        ) : failedWithoutData ? (
          <div className="flex flex-col items-start gap-2 px-1 py-2">
            <span className="text-[13px] text-gray-10">
              Couldn't load reviewers. Try again.
            </span>
            <Button
              type="button"
              variant="outline"
              size="xs"
              onClick={() => {
                if (artefactsError) void refetchArtefacts();
                if (availableReviewersError) void refetchAvailableReviewers();
              }}
            >
              Retry
            </Button>
          </div>
        ) : options.length === 0 ? (
          <span className="block px-1 py-2 text-[13px] text-gray-10">
            No users found.
          </span>
        ) : (
          <div className="flex flex-col">
            {options.map((option) => {
              const assigned = reviewers.some((reviewer) =>
                reviewerMatchesAvailable(reviewer, option),
              );
              return (
                <button
                  key={option.uuid}
                  type="button"
                  aria-pressed={assigned}
                  disabled={isPending}
                  className="flex w-full items-center justify-between gap-2 rounded-(--radius-1) px-1 py-1 text-left text-[13px] text-gray-12 transition-colors hover:bg-(--gray-3) focus-visible:bg-(--gray-3) focus-visible:outline-none disabled:opacity-60"
                  onClick={() => toggleReviewer(option)}
                >
                  <span className="flex min-w-0 items-center gap-2">
                    {option.github_login ? (
                      <SuggestedReviewerAvatar
                        githubLogin={option.github_login}
                        size="sm"
                      />
                    ) : null}
                    <span className="flex min-w-0 flex-col">
                      <span className="truncate">
                        {getSuggestedReviewerDisplayName(option)}
                      </span>
                      {option.email ? (
                        <span className="truncate text-[12px] text-gray-10">
                          {option.email}
                        </span>
                      ) : null}
                    </span>
                  </span>
                  <span
                    className="flex h-4 w-4 shrink-0 items-center justify-center"
                    aria-hidden
                  >
                    {assigned ? <CheckIcon size={12} weight="bold" /> : null}
                  </span>
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
