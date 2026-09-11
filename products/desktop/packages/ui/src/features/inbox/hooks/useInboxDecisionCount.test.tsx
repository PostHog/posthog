import { INBOX_SCOPE_ENTIRE_PROJECT } from "@posthog/core/inbox/reportMembership";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mockGetSignalReports = vi.hoisted(() => vi.fn());
const filterMocks = vi.hoisted(() => ({
  priorityFilter: ["P1"] as string[],
  reportStateFilter: ["review_and_merge", "needs_decision"] as string[],
}));

vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => ({
    getSignalReports: mockGetSignalReports,
  }),
}));
vi.mock("@posthog/ui/features/auth/useCurrentUser", () => ({
  AUTH_SCOPED_QUERY_META: {},
  useCurrentUser: () => ({ data: null }),
}));
vi.mock("@posthog/ui/features/inbox/stores/inboxReviewerScopeStore", () => ({
  useInboxReviewerScopeStore: (
    selector: (state: { scope: string }) => unknown,
  ) => selector({ scope: INBOX_SCOPE_ENTIRE_PROJECT }),
}));
vi.mock("@posthog/ui/features/inbox/stores/inboxSignalsFilterStore", () => ({
  useInboxSignalsFilterStore: (selector: (state: unknown) => unknown) =>
    selector({
      priorityFilter: filterMocks.priorityFilter,
      reportStateFilter: filterMocks.reportStateFilter,
    }),
}));

import { useInboxDecisionCount } from "./useInboxDecisionCount";

function renderCount(enabled: boolean) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return renderHook(() => useInboxDecisionCount({ enabled }), { wrapper });
}

describe("useInboxDecisionCount", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    filterMocks.priorityFilter = ["P1"];
    filterMocks.reportStateFilter = ["review_and_merge", "needs_decision"];
    mockGetSignalReports.mockImplementation(async (params) => ({
      count: params.has_implementation_pr ? 2 : 3,
      results: [],
    }));
  });

  it("counts the active report groups with the configured priority filter", async () => {
    const { result } = renderCount(true);

    await waitFor(() => expect(result.current).toBe(5));
    expect(mockGetSignalReports).toHaveBeenCalledTimes(2);
    expect(mockGetSignalReports.mock.calls.map(([params]) => params)).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          count_only: true,
          has_implementation_pr: true,
          priority: "P1",
          status: "ready",
        }),
        expect.objectContaining({
          actionability: "immediately_actionable,requires_human_input",
          count_only: true,
          has_implementation_pr: false,
          priority: "P1",
          status: "ready,pending_input",
        }),
      ]),
    );
  });

  it("shows no badge when the status filter hides active reports", () => {
    filterMocks.reportStateFilter = ["resolved", "dismissed"];

    expect(renderCount(true).result.current).toBe(0);
    expect(mockGetSignalReports).not.toHaveBeenCalled();
  });

  it("does not request a count when the navigation item is unavailable", () => {
    expect(renderCount(false).result.current).toBe(0);
    expect(mockGetSignalReports).not.toHaveBeenCalled();
  });
});
