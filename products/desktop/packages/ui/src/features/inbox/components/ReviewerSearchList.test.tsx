import type { SignalReport } from "@posthog/shared/types";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  updateReviewers: vi.fn(),
  trackAction: vi.fn(),
  trackResult: vi.fn(),
  refetchAvailable: vi.fn(),
  availableError: false,
}));

vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => ({}),
}));

vi.mock("@posthog/ui/features/auth/useCurrentUser", () => ({
  useCurrentUser: () => ({ data: { uuid: "current-user" } }),
}));

vi.mock("@posthog/ui/features/inbox/hooks/useInboxReports", () => ({
  useInboxReportArtefacts: () => ({
    data: { count: 0, results: [] },
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  }),
  useInboxAvailableSuggestedReviewers: () => ({
    data: mocks.availableError
      ? undefined
      : {
          count: 1,
          results: [
            {
              uuid: "reviewer-1",
              name: "Ada Lovelace",
              email: "ada@example.com",
              github_login: "ada",
            },
          ],
        },
    isFetching: false,
    isError: mocks.availableError,
    refetch: mocks.refetchAvailable,
  }),
  useUpdateSuggestedReviewers: () => ({
    mutate: mocks.updateReviewers,
    isPending: false,
  }),
}));

vi.mock("@posthog/ui/features/inbox/hooks/useReportActionTracker", () => ({
  useReportActionTracker: () => mocks.trackAction,
  useReportActionResultTracker: () => mocks.trackResult,
}));

import { ReviewerSearchList } from "./ReviewerSearchList";

const report: SignalReport = {
  id: "report-1",
  title: "Report one",
  summary: "Summary",
  status: "ready",
  total_weight: 1,
  signal_count: 1,
  artefact_count: 0,
  created_at: "2026-08-20T09:00:00Z",
  updated_at: "2026-08-20T09:00:00Z",
};

describe("ReviewerSearchList", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.availableError = false;
  });

  it("assigns the first reviewer when the report has no reviewer artefact", async () => {
    render(<ReviewerSearchList report={report} surface="context_menu" />);

    await userEvent.click(screen.getByText("Ada Lovelace"));

    expect(mocks.updateReviewers).toHaveBeenCalledWith(
      {
        content: [{ user_uuid: "reviewer-1" }],
        optimisticReviewers: [
          expect.objectContaining({
            github_login: "ada",
            user: expect.objectContaining({ uuid: "reviewer-1" }),
          }),
        ],
      },
      expect.objectContaining({
        onSuccess: expect.any(Function),
        onError: expect.any(Function),
      }),
    );

    const callbacks = mocks.updateReviewers.mock.calls[0][1];
    callbacks.onSuccess();
    expect(mocks.trackResult).toHaveBeenCalledWith(
      "add_suggested_reviewer",
      "succeeded",
      expect.any(Number),
    );
  });

  it("shows reviewer load failures with a retry action", async () => {
    mocks.availableError = true;
    render(<ReviewerSearchList report={report} surface="context_menu" />);

    expect(
      screen.getByText("Couldn't load reviewers. Try again."),
    ).toBeTruthy();
    await userEvent.click(screen.getByText("Retry"));

    expect(mocks.refetchAvailable).toHaveBeenCalledOnce();
    expect(screen.queryByText("No users found.")).toBeNull();
  });
});
