import type {
  SignalReport,
  SignalReportArtefactsResponse,
  SuggestedReviewer,
} from "@posthog/shared/types";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  currentUserUuid: "user-me",
  mutate: vi.fn(),
  trackAction: vi.fn(),
  lastSurface: undefined as string | undefined,
}));

vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => ({}),
}));

vi.mock("@posthog/ui/features/auth/useCurrentUser", () => ({
  useCurrentUser: () => ({ data: { uuid: mocks.currentUserUuid } }),
}));

vi.mock("@posthog/ui/features/inbox/hooks/useInboxReports", () => ({
  useInboxReportArtefacts: () => ({ data: undefined }),
  useUpdateSuggestedReviewers: () => ({
    mutate: mocks.mutate,
    isPending: false,
  }),
}));

vi.mock("@posthog/ui/features/inbox/hooks/useReportActionTracker", () => ({
  useReportActionTracker: (_report: unknown, surface?: string) => {
    mocks.lastSurface = surface;
    return mocks.trackAction;
  },
}));

import { SuggestedReviewerAvatarStack } from "./SuggestedReviewerAvatarStack";

function reviewer(login: string, uuid: string): SuggestedReviewer {
  return {
    github_login: login,
    github_name: login,
    relevant_commits: [],
    user: {
      id: 1,
      uuid,
      email: `${login}@example.com`,
      first_name: login,
      last_name: "",
    },
  };
}

const me = reviewer("alice", "user-me");
me.relevant_commits = [
  {
    sha: "abc123",
    url: "https://github.com/example/repo/commit/abc123",
    reason: "Recently changed the affected request parser.",
  },
];
const teammate = reviewer("bob", "user-bob");
const report = {
  id: "report-1",
  title: "Investigate checkout failures",
  summary: "Checkout failures increased.",
  status: "ready",
  total_weight: 1,
  signal_count: 1,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  artefact_count: 1,
  is_suggested_reviewer: true,
} satisfies SignalReport;
const artefacts = {
  count: 1,
  results: [
    {
      id: "reviewers-1",
      type: "suggested_reviewers",
      created_at: "2026-01-01T00:00:00Z",
      content: [me, teammate],
    },
  ],
} satisfies SignalReportArtefactsResponse;

describe("SuggestedReviewerAvatarStack", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.currentUserUuid = "user-me";
    mocks.lastSurface = undefined;
  });

  it.each([
    ["defaults to the list-row surface", undefined, "list_row"],
    ["uses the surface it is given", "detail_pane", "detail_pane"],
  ] as const)("%s", (_case, surface, expected) => {
    render(
      <SuggestedReviewerAvatarStack
        report={report}
        artefacts={artefacts}
        surface={surface}
      />,
    );
    expect(mocks.lastSurface).toBe(expected);
  });

  it.each([
    ["the current user is assigned", "user-me", true],
    ["the current user is not assigned", "user-other", false],
  ])("offers removal when %s", async (_case, currentUserUuid, canRemove) => {
    const user = userEvent.setup();
    mocks.currentUserUuid = currentUserUuid;
    render(
      <SuggestedReviewerAvatarStack report={report} artefacts={artefacts} />,
    );

    await user.click(
      screen.getByRole("button", {
        name: "View suggested reviewer rationale",
      }),
    );
    const removeButton = screen.queryByRole("button", {
      name: "Remove me from reviewers",
    });
    expect(!!removeButton).toBe(canRemove);
    expect(screen.getByText("2 suggested reviewers")).toBeTruthy();
  });

  it("removes the current user and tracks the list action", async () => {
    const onCardClick = vi.fn();
    const user = userEvent.setup();
    document.addEventListener("click", onCardClick);
    render(
      <SuggestedReviewerAvatarStack report={report} artefacts={artefacts} />,
    );

    await user.click(
      screen.getByRole("button", {
        name: "View suggested reviewer rationale",
      }),
    );
    const button = await screen.findByRole("button", {
      name: "Remove me from reviewers",
    });
    expect(
      screen.getByText("Recently changed the affected request parser."),
    ).toBeTruthy();

    await user.click(button);

    expect(onCardClick).not.toHaveBeenCalled();
    expect(mocks.mutate).toHaveBeenCalledWith({
      artefactId: "reviewers-1",
      content: [{ github_login: "bob" }],
      optimisticReviewers: [teammate],
    });
    expect(mocks.trackAction).toHaveBeenCalledWith(
      "remove_suggested_reviewer",
      {
        suggested_reviewer_login: "alice",
        suggested_reviewer_uuid: "user-me",
      },
    );
    document.removeEventListener("click", onCardClick);
  });
});
