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
const mockTrack = vi.hoisted(() => vi.fn());

vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => ({
    getSignalReports: mockGetSignalReports,
  }),
}));

vi.mock("@posthog/ui/features/auth/useCurrentUser", () => ({
  AUTH_SCOPED_QUERY_META: {},
  useCurrentUser: () => ({ data: { uuid: "user-1" } }),
}));

vi.mock("@posthog/ui/shell/analytics", () => ({ track: mockTrack }));

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
import { useTrackInboxViewed } from "./useTrackInboxViewed";

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

/**
 * Renders the tracker with a probe alongside it, so tests can await the list's
 * load state. The probe deliberately omits `withReportsCount`: opting in here
 * would enable the count query itself, and the tracker would then read it from
 * the cache even when the tracker never asked for it.
 */
function renderTracker() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return renderHook(
    () => {
      useTrackInboxViewed();
      return useInboxAllReports();
    },
    { wrapper },
  );
}

function trackedProperties(): Record<string, unknown> {
  return mockTrack.mock.calls[0][1] as Record<string, unknown>;
}

describe("useTrackInboxViewed", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetSignalReports.mockImplementation(async (params) =>
      fakeServer(params),
    );
  });

  it("records the tab counts the badges show", async () => {
    renderTracker();

    await waitFor(() => expect(mockTrack).toHaveBeenCalledTimes(1));
    expect(trackedProperties()).toMatchObject({
      pulls_tab_count: PULL_REQUEST_TOTAL,
      reports_tab_count: REPORT_TAB_TOTAL,
    });
  });

  it("holds the one-shot event until the count requests land", async () => {
    let releaseReportsCount: (response: SignalReportsResponse) => void =
      () => {};
    const pendingReportsCount = new Promise<SignalReportsResponse>(
      (resolve) => {
        releaseReportsCount = resolve;
      },
    );
    mockGetSignalReports.mockImplementation((params) =>
      params?.has_implementation_pr === false
        ? pendingReportsCount
        : Promise.resolve(fakeServer(params)),
    );

    const { result } = renderTracker();

    // The list resolving first is the whole point: the event must not fire on it.
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockTrack).not.toHaveBeenCalled();

    releaseReportsCount({ count: REPORT_TAB_TOTAL, results: [] });

    await waitFor(() => expect(mockTrack).toHaveBeenCalledTimes(1));
    expect(trackedProperties()).toMatchObject({
      reports_tab_count: REPORT_TAB_TOTAL,
    });
  });
});
