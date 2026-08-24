import {
  CheckIcon,
  MagnifyingGlassIcon,
  PlusIcon,
} from "@phosphor-icons/react";
import { toSuggestedReviewerWriteContent } from "@posthog/core/inbox/artefacts";
import { selectSuggestedReviewersArtefact } from "@posthog/core/inbox/reportArtefacts";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
  Spinner,
} from "@posthog/quill";
import type {
  AvailableSuggestedReviewer,
  SignalReport,
  SuggestedReviewer,
} from "@posthog/shared/types";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
import { SuggestedReviewerAvatarStack } from "@posthog/ui/features/inbox/components/SuggestedReviewerAvatarStack";
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
import { useReportActionTracker } from "@posthog/ui/features/inbox/hooks/useReportActionTracker";
import { useDeferredValue, useMemo, useState } from "react";

function reviewerMatchesAvailable(
  reviewer: SuggestedReviewer,
  available: AvailableSuggestedReviewer,
): boolean {
  if (reviewer.user?.uuid && reviewer.user.uuid === available.uuid) {
    return true;
  }
  return (
    !!reviewer.github_login &&
    !!available.github_login &&
    reviewer.github_login.toLowerCase() === available.github_login.toLowerCase()
  );
}

/**
 * Reviewers as header furniture: the avatar stack plus an add/remove popover.
 * Replaces the right-column Reviewers card and its per-reviewer commit
 * reasoning — who is on the hook matters here, the why lives on the PR.
 */
export function ReportReviewersHeader({ report }: { report: SignalReport }) {
  const client = useOptionalAuthenticatedClient();
  const fireAction = useReportActionTracker(report);
  const { data: currentUser } = useCurrentUser({ client, enabled: !!client });
  const { data: artefactsResp } = useInboxReportArtefacts(report.id);
  const artefact = selectSuggestedReviewersArtefact(
    artefactsResp?.results ?? [],
  );

  const [addOpen, setAddOpen] = useState(false);
  const [query, setQuery] = useState("");
  const deferredQuery = useDeferredValue(query);

  const { mutate: updateReviewers, isPending } = useUpdateSuggestedReviewers(
    report.id,
  );
  const { data: availableReviewers, isFetching } =
    useInboxAvailableSuggestedReviewers({
      enabled: !!client && addOpen,
      query: deferredQuery,
    });

  const reviewers = useMemo(() => artefact?.content ?? [], [artefact]);

  const options = useMemo(() => {
    const built = buildSuggestedReviewerFilterOptions(
      availableReviewers?.results ?? [],
      currentUser,
    );
    const q = deferredQuery.trim().toLowerCase();
    if (!q) return built;
    return built.filter(
      (option) =>
        option.name.toLowerCase().includes(q) ||
        option.email.toLowerCase().includes(q) ||
        option.github_login.toLowerCase().includes(q),
    );
  }, [availableReviewers?.results, currentUser, deferredQuery]);

  if (!artefact) return null;

  const toggleReviewer = (option: AvailableSuggestedReviewer) => {
    const existing = reviewers.find((r) => reviewerMatchesAvailable(r, option));
    if (existing) {
      const next = reviewers.filter((r) => r !== existing);
      fireAction("remove_suggested_reviewer", {
        suggested_reviewer_login: existing.github_login || undefined,
        suggested_reviewer_uuid: existing.user?.uuid,
      });
      updateReviewers({
        artefactId: artefact.id,
        content: toSuggestedReviewerWriteContent(next),
        optimisticReviewers: next,
      });
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
    updateReviewers({
      artefactId: artefact.id,
      content: [
        ...toSuggestedReviewerWriteContent(reviewers),
        { user_uuid: option.uuid },
      ],
      optimisticReviewers: [...reviewers, optimisticEntry],
    });
  };

  return (
    <div className="flex items-center gap-1.5">
      <SuggestedReviewerAvatarStack
        report={report}
        artefacts={artefactsResp}
        surface="detail_pane"
      />
      <Popover
        open={addOpen}
        onOpenChange={(next) => {
          setAddOpen(next);
          if (!next) setQuery("");
        }}
      >
        <PopoverTrigger
          render={
            <button
              type="button"
              aria-label="Add or remove reviewers"
              className="flex h-5 w-5 items-center justify-center rounded-full border border-(--gray-6) border-dashed text-(--gray-9) transition-colors hover:border-(--gray-8) hover:text-gray-12"
            >
              {isPending ? <Spinner /> : <PlusIcon size={10} />}
            </button>
          }
        />
        <PopoverContent
          align="end"
          side="bottom"
          sideOffset={6}
          className="flex min-w-[280px] max-w-[320px] flex-col gap-2 p-2"
        >
          <div className="flex items-center gap-2 rounded-(--radius-2) border border-(--gray-6) bg-(--color-background) px-2 py-1">
            <MagnifyingGlassIcon size={12} className="shrink-0 text-gray-10" />
            <input
              type="text"
              placeholder="Filter users…"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              className="min-w-0 flex-1 bg-transparent text-[13px] text-gray-12 outline-none placeholder:text-(--gray-9)"
            />
          </div>
          <div className="max-h-[280px] overflow-y-auto">
            {isFetching && !availableReviewers?.results?.length ? (
              <div className="flex items-center justify-center py-3">
                <Spinner />
              </div>
            ) : options.length === 0 ? (
              <span className="block px-1 py-2 text-[13px] text-gray-10">
                No users found.
              </span>
            ) : (
              <div className="flex flex-col">
                {options.map((option) => {
                  const assigned = reviewers.some((r) =>
                    reviewerMatchesAvailable(r, option),
                  );
                  return (
                    <button
                      key={option.uuid}
                      type="button"
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
                        {assigned ? (
                          <CheckIcon size={12} weight="bold" />
                        ) : null}
                      </span>
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        </PopoverContent>
      </Popover>
    </div>
  );
}
