import type { SignalReport } from "@posthog/shared/types";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { getSignalReport, preloadRoute } = vi.hoisted(() => ({
  getSignalReport: vi.fn(),
  preloadRoute: vi.fn(),
}));

vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => ({ getSignalReport }),
}));

vi.mock("@tanstack/react-router", () => ({
  useRouter: () => ({ preloadRoute }),
}));

import { inboxReportDetailQueryKey } from "@posthog/core/inbox/inboxQuery";
import { useInboxReportDetailPrefetch } from "./useInboxReportDetailPrefetch";
import { useInboxReportById } from "./useInboxReports";

const report: SignalReport = {
  id: "report-1",
  title: "Report",
  summary: "Summary",
  status: "ready",
  total_weight: 1,
  signal_count: 1,
  created_at: "2026-01-01T00:00:00.000Z",
  updated_at: "2026-01-01T00:00:00.000Z",
  artefact_count: 0,
  priority: "P2",
  actionability: "immediately_actionable",
  is_suggested_reviewer: false,
  source_products: [],
  implementation_pr_url: null,
};

describe("useInboxReportDetailPrefetch", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getSignalReport.mockResolvedValue(report);
  });

  it("warms the authenticated report query before navigation", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(
      () =>
        useInboxReportDetailPrefetch({
          to: "/inbox/reports/$reportId",
          params: { reportId: report.id },
        }),
      { wrapper },
    );

    act(() => result.current.pointerHandlers.onPointerEnter());

    await waitFor(() =>
      expect(getSignalReport).toHaveBeenCalledWith(report.id),
    );
    expect(preloadRoute).not.toHaveBeenCalled();

    act(() => result.current.prefetch());
    expect(preloadRoute).toHaveBeenCalledWith({
      to: "/inbox/reports/$reportId",
      params: { reportId: report.id },
    });

    const queryKey = inboxReportDetailQueryKey(report.id);
    await waitFor(() =>
      expect(queryClient.getQueryData(queryKey)).toEqual(report),
    );
    expect(queryClient.getQueryCache().find({ queryKey })?.meta).toEqual({
      authScoped: true,
    });

    const detail = renderHook(() => useInboxReportById(report.id), { wrapper });
    await waitFor(() => expect(detail.result.current.data).toEqual(report));
    expect(getSignalReport).toHaveBeenCalledTimes(1);

    queryClient.removeQueries({
      predicate: (query) => query.meta?.authScoped === true,
    });
    expect(queryClient.getQueryData(queryKey)).toBeUndefined();
  });
});
