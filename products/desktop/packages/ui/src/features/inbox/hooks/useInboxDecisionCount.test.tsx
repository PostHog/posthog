import { INBOX_SCOPE_ENTIRE_PROJECT } from "@posthog/core/inbox/reportMembership";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mockGetSignalReports = vi.hoisted(() => vi.fn());

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
    mockGetSignalReports.mockResolvedValue({ count: 7, results: [] });
  });

  it("loads only a one-row server count for the navigation badge", async () => {
    const { result } = renderCount(true);

    await waitFor(() => expect(result.current).toBe(7));
    expect(mockGetSignalReports).toHaveBeenCalledOnce();
    expect(mockGetSignalReports).toHaveBeenCalledWith(
      expect.objectContaining({
        limit: 1,
        priority: undefined,
        source_product: undefined,
        status: "ready",
      }),
    );
  });

  it("does not request a count when the navigation item is unavailable", () => {
    expect(renderCount(false).result.current).toBe(0);
    expect(mockGetSignalReports).not.toHaveBeenCalled();
  });
});
