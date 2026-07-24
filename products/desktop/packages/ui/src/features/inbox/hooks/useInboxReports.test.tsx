import type {
  SignalReportArtefactsResponse,
  SuggestedReviewer,
  SuggestedReviewersArtefact,
} from "@posthog/shared/domain-types";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook } from "@testing-library/react";
import { act, type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mockUpdateArtefact = vi.hoisted(() => vi.fn());
const mockClient = vi.hoisted(() => ({
  updateSignalReportArtefact: mockUpdateArtefact,
}));

vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => mockClient,
}));

vi.mock("@posthog/ui/primitives/toast", () => ({
  toast: { error: vi.fn() },
}));

import { reportKeys, useUpdateSuggestedReviewers } from "./useInboxReports";

const REPORT_ID = "report-1";
const ARTEFACT_ID = "art-1";

function reviewer(login: string, uuid?: string): SuggestedReviewer {
  return {
    github_login: login,
    github_name: login,
    relevant_commits: [],
    user: uuid
      ? {
          id: 1,
          uuid,
          email: `${login}@x.io`,
          first_name: login,
          last_name: "",
        }
      : null,
  };
}

function artefact(content: SuggestedReviewer[]): SuggestedReviewersArtefact {
  return {
    id: ARTEFACT_ID,
    type: "suggested_reviewers",
    created_at: "2024-01-01T00:00:00Z",
    content,
  };
}

function renderUpdateHook() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  const result = renderHook(() => useUpdateSuggestedReviewers(REPORT_ID), {
    wrapper,
  });
  return { ...result, queryClient };
}

describe("useUpdateSuggestedReviewers", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("optimistically appends a new latest reviewers row, keeping the prior one", async () => {
    mockUpdateArtefact.mockResolvedValue(artefact([reviewer("octocat")]));
    const { result, queryClient } = renderUpdateHook();

    const key = reportKeys.artefacts(REPORT_ID);
    queryClient.setQueryData<SignalReportArtefactsResponse>(key, {
      results: [artefact([reviewer("octocat"), reviewer("hubot")])],
      count: 1,
    });

    const next = [reviewer("octocat")];
    await act(async () => {
      await result.current.mutateAsync({
        artefactId: ARTEFACT_ID,
        content: [{ github_login: "octocat" }],
        optimisticReviewers: next,
      });
    });

    expect(mockUpdateArtefact).toHaveBeenCalledWith(REPORT_ID, ARTEFACT_ID, [
      { github_login: "octocat" },
    ]);

    const cached = queryClient.getQueryData<SignalReportArtefactsResponse>(key);
    const reviewerRows = (cached?.results ?? []).filter(
      (a): a is SuggestedReviewersArtefact => a.type === "suggested_reviewers",
    );
    // The prior row is preserved untouched as history.
    const priorRow = reviewerRows.find((a) => a.id === ARTEFACT_ID);
    expect(priorRow?.content.map((r) => r.github_login)).toEqual([
      "octocat",
      "hubot",
    ]);
    // A new synthetic row is appended and is the latest (current reviewers).
    const latest = reviewerRows.reduce((a, b) =>
      a.created_at > b.created_at ? a : b,
    );
    expect(latest.id).not.toBe(ARTEFACT_ID);
    expect(latest.content.map((r) => r.github_login)).toEqual(["octocat"]);
  });

  it("rolls back the cache when the request fails", async () => {
    const failure = new Error("boom");
    mockUpdateArtefact.mockRejectedValue(failure);
    const { result, queryClient } = renderUpdateHook();

    const key = reportKeys.artefacts(REPORT_ID);
    const original = [reviewer("octocat"), reviewer("hubot")];
    queryClient.setQueryData<SignalReportArtefactsResponse>(key, {
      results: [artefact(original)],
      count: 1,
    });

    let caught: unknown;
    await act(async () => {
      try {
        await result.current.mutateAsync({
          artefactId: ARTEFACT_ID,
          content: [{ github_login: "octocat" }],
          optimisticReviewers: [reviewer("octocat")],
        });
      } catch (error) {
        caught = error;
      }
    });
    expect(caught).toBe(failure);

    const cached = queryClient.getQueryData<SignalReportArtefactsResponse>(key);
    const cachedArtefact = cached?.results.find((a) => a.id === ARTEFACT_ID) as
      | SuggestedReviewersArtefact
      | undefined;
    expect(cachedArtefact?.content.map((r) => r.github_login)).toEqual([
      "octocat",
      "hubot",
    ]);
  });
});
