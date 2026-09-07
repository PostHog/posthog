import { inboxReportDetailQueryKey } from "@posthog/core/inbox/inboxQuery";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import type { SignalReport } from "@posthog/shared/types";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  updateState: vi.fn(),
  track: vi.fn(),
}));

vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => ({
    updateSignalReportState: mocks.updateState,
  }),
}));

vi.mock("@posthog/ui/features/auth/useCurrentUser", () => ({
  useCurrentUser: () => ({ data: { uuid: "user-1" } }),
}));

vi.mock("@posthog/ui/shell/analytics", () => ({
  track: mocks.track,
}));

import { useInboxBulkActions } from "./useInboxBulkActions";

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
  dismissal_note: "Old note",
};

function createWrapper(queryClient: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
  };
}

describe("useInboxBulkActions", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("keeps report metadata for analytics after an optimistic rerender", async () => {
    let finishRequest: (() => void) | undefined;
    mocks.updateState.mockReturnValue(
      new Promise<void>((resolve) => {
        finishRequest = resolve;
      }),
    );
    const queryClient = new QueryClient({
      defaultOptions: { mutations: { retry: false } },
    });
    const { result, rerender } = renderHook(
      ({ reports }) => useInboxBulkActions(reports, report.id, "list_row"),
      {
        initialProps: { reports: [report] },
        wrapper: createWrapper(queryClient),
      },
    );

    let action = Promise.resolve(false);
    act(() => {
      action = result.current.suppressSelected({ reason: "other", note: "" });
    });
    await waitFor(() => expect(mocks.updateState).toHaveBeenCalledOnce());
    rerender({ reports: [] });
    await act(async () => finishRequest?.());

    await expect(action).resolves.toBe(true);
    expect(mocks.track).toHaveBeenCalledWith(
      ANALYTICS_EVENTS.INBOX_REPORT_ACTION,
      expect.objectContaining({ report_id: report.id, action_type: "dismiss" }),
    );
  });

  it("clears a stale note in the optimistic report", async () => {
    mocks.updateState.mockReturnValue(new Promise<void>(() => {}));
    const queryClient = new QueryClient({
      defaultOptions: { mutations: { retry: false } },
    });
    queryClient.setQueryData(inboxReportDetailQueryKey(report.id), report);
    const { result } = renderHook(
      () => useInboxBulkActions([report], report.id),
      { wrapper: createWrapper(queryClient) },
    );

    act(() => {
      void result.current.suppressSelected({ reason: "other", note: "" });
    });

    await waitFor(() =>
      expect(
        queryClient.getQueryData<SignalReport>(
          inboxReportDetailQueryKey(report.id),
        )?.dismissal_note,
      ).toBeNull(),
    );
  });

  it("returns false when any selected dismissal fails", async () => {
    mocks.updateState.mockRejectedValue(new Error("Request failed"));
    const queryClient = new QueryClient({
      defaultOptions: { mutations: { retry: false } },
    });
    const { result } = renderHook(
      () => useInboxBulkActions([report], report.id),
      { wrapper: createWrapper(queryClient) },
    );

    await expect(
      result.current.suppressSelected({ reason: "other", note: "" }),
    ).resolves.toBe(false);
  });
});
