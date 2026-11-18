import { INBOX_SCOPE_ENTIRE_PROJECT } from "@posthog/core/inbox/reportMembership";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mockGetSectionCounts = vi.hoisted(() => vi.fn());

vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => ({
    getSignalReportSectionCounts: mockGetSectionCounts,
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
      sourceProductFilter: ["github"],
      priorityFilter: ["P1"],
      prFilter: "all",
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
  return renderHook(
    () => useInboxDecisionCount({ enabled, ignoreFilters: true }),
    { wrapper },
  );
}

describe("useInboxDecisionCount", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetSectionCounts.mockResolvedValue({ pull_requests: 3, reports: 4 });
  });

  it("sums the server's ready counts for the navigation badge", async () => {
    const { result } = renderCount(true);

    await waitFor(() => expect(result.current).toBe(7));
    expect(mockGetSectionCounts).toHaveBeenCalledOnce();
    expect(mockGetSectionCounts).toHaveBeenCalledWith(
      expect.objectContaining({
        priority: undefined,
        source_product: undefined,
      }),
    );
  });

  it("does not request a count when the navigation item is unavailable", () => {
    expect(renderCount(false).result.current).toBe(0);
    expect(mockGetSectionCounts).not.toHaveBeenCalled();
  });
});
