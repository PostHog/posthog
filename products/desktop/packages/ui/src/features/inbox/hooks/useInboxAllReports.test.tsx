import { INBOX_SCOPE_ENTIRE_PROJECT } from "@posthog/core/inbox/reportMembership";
import type {
  SignalReport,
  SignalReportsQueryParams,
  SignalReportsResponse,
} from "@posthog/shared/domain-types";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const PIPELINE_TOTAL = 240;
const PULL_REQUEST_TOTAL = 40;
const REPORT_TAB_TOTAL = 75;

const mockGetSignalReports = vi.hoisted(() => vi.fn());
const mockClient = vi.hoisted(() => ({
  getSignalReports: mockGetSignalReports,
}));

vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => mockClient,
}));

vi.mock("@posthog/ui/features/auth/useCurrentUser", () => ({
  AUTH_SCOPED_QUERY_META: {},
  useCurrentUser: () => ({ data: { uuid: "user-1" } }),
}));

vi.mock("@posthog/ui/features/inbox/stores/inboxReviewerScopeStore", () => ({
  useInboxReviewerScopeStore: (
    selector: (state: { scope: string }) => unknown,
  ) => selector({ scope: INBOX_SCOPE_ENTIRE_PROJECT }),
}));

vi.mock("@posthog/ui/features/inbox/stores/inboxSignalsFilterStore", () => ({
  useInboxSignalsFilterStore: (selector: (state: unknown) => unknown) =>
    selector({
      searchQuery: "",
      sortField: "priority",
      sortDirection: "desc",
      sourceProductFilter: [],
      priorityFilter: [],
    }),
}));

import { useInboxAllReports } from "./useInboxAllReports";

function readyReport(index: number): SignalReport {
  return {
    id: `report-${index}`,
    title: `Report ${index}`,
    summary: null,
    status: "ready",
    total_weight: 1,
    signal_count: 1,
    created_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:00Z",
    artefact_count: 0,
    implementation_pr_url: null,
  };
}

/**
 * Answers the three distinct queries the hook fires. The pipeline page is all
 * `ready` reports with no PR, which is what the server's status-ranked ordering
 * actually returns first, and is the condition under which deriving the Reports
 * badge by subtraction silently overcounts.
 */
function fakeServer(params?: SignalReportsQueryParams): SignalReportsResponse {
  if (params?.has_implementation_pr === true) {
    return { count: PULL_REQUEST_TOTAL, results: [] };
  }
  if (params?.has_implementation_pr === false) {
    return { count: REPORT_TAB_TOTAL, results: [] };
  }
  return {
    count: PIPELINE_TOTAL,
    results: Array.from({ length: 100 }, (_, i) => readyReport(i)),
  };
}

/** Params of the Reports-count request, or undefined if it was never fired. */
function reportsCountParams(): SignalReportsQueryParams | undefined {
  for (const [params] of mockGetSignalReports.mock.calls) {
    if (params?.has_implementation_pr === false) return params;
  }
  return undefined;
}

function renderCounts(options?: {
  enabled?: boolean;
  withReportsCount?: boolean;
}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return renderHook(() => useInboxAllReports(options), { wrapper });
}

describe("useInboxAllReports", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetSignalReports.mockImplementation(async (params) =>
      fakeServer(params),
    );
  });

  it("counts Reports from the server, not by subtracting from the pipeline total", async () => {
    const { result } = renderCounts({ withReportsCount: true });

    await waitFor(() => {
      expect(result.current.counts.reports).toBe(REPORT_TAB_TOTAL);
    });
    expect(result.current.counts.pulls).toBe(PULL_REQUEST_TOTAL);

    // Anything wider than `ready` pulls in the queued, live and failed runs that
    // the Reports tab routes elsewhere, which is what made the badge disagree
    // with the list it labels.
    expect(reportsCountParams()?.status).toBe("ready");
  });

  it("skips the Reports count query for consumers that only read the pulls badge", async () => {
    const { result } = renderCounts();

    await waitFor(() => {
      expect(result.current.counts.pulls).toBe(PULL_REQUEST_TOTAL);
    });
    expect(result.current.counts.reports).toBe(0);
    expect(reportsCountParams()).toBeUndefined();
  });

  it("does not request reports when its surface is unavailable", () => {
    renderCounts({ enabled: false, withReportsCount: true });

    expect(mockGetSignalReports).not.toHaveBeenCalled();
  });
});
