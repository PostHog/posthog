import { ANALYTICS_EVENTS } from "@posthog/shared";
import type { SignalReport } from "@posthog/shared/types";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  refundSignalReport: vi.fn(),
  track: vi.fn(),
  success: vi.fn(),
  error: vi.fn(),
}));

vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useAuthenticatedClient: () => ({
    refundSignalReport: mocks.refundSignalReport,
  }),
}));

vi.mock("@posthog/ui/features/feature-flags/useFeatureFlag", () => ({
  useFeatureFlag: () => true,
}));

vi.mock("@posthog/ui/shell/analytics", () => ({ track: mocks.track }));

vi.mock("@posthog/ui/primitives/toast", () => ({
  toast: { success: mocks.success, error: mocks.error },
}));

import { useRefundReport } from "./useRefundReport";

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
  implementation_pr_url: "https://github.com/PostHog/posthog/pull/1",
};

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { mutations: { retry: false } },
  });
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
  };
}

describe("useRefundReport", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.refundSignalReport.mockResolvedValue({
      ...report,
      status: "suppressed",
    });
  });

  it("tracks the refund reason and note after a successful refund", async () => {
    const { result } = renderHook(() => useRefundReport(report), {
      wrapper: createWrapper(),
    });

    await act(async () => {
      await result.current.mutation.mutateAsync({
        reason: "pr_incorrect",
        note: "The proposed change did not fix the issue",
      });
    });

    expect(mocks.track).toHaveBeenCalledWith(
      ANALYTICS_EVENTS.INBOX_REPORT_ACTION,
      expect.objectContaining({
        report_id: report.id,
        action_type: "refund",
        refund_reason: "pr_incorrect",
        refund_note: "The proposed change did not fix the issue",
      }),
    );
  });
});
