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
  success: vi.fn(),
  error: vi.fn(),
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

vi.mock("@posthog/ui/primitives/toast", () => ({
  toast: { success: mocks.success, error: mocks.error },
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

  it.each([
    ["suppressSelected", "dismiss", "other"],
    ["snoozeSelected", "snooze", "already_fixed"],
  ] as const)(
    "%s confirms success after an optimistic rerender",
    async (actionName, actionType, reason) => {
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
        action = result.current[actionName]({
          reason,
          note: "",
        });
      });
      await waitFor(() => expect(mocks.updateState).toHaveBeenCalledOnce());
      expect(mocks.success).not.toHaveBeenCalled();
      rerender({ reports: [] });
      await act(async () => finishRequest?.());

      await expect(action).resolves.toBe(true);
      expect(mocks.track).toHaveBeenCalledWith(
        ANALYTICS_EVENTS.INBOX_REPORT_ACTION,
        expect.objectContaining({
          report_id: report.id,
          action_type: actionType,
        }),
      );
      expect(mocks.success).toHaveBeenCalledOnce();
    },
  );

  it.each([
    ["potential", false, true],
    ["candidate", false, true],
    ["in_progress", true, true],
    ["pending_input", true, true],
    ["ready", true, true],
    ["failed", true, true],
    ["suppressed", false, false],
    ["resolved", false, false],
    ["deleted", false, false],
  ] as const)(
    "%s has separate pause and archive eligibility",
    async (status, canPause, canArchive) => {
      mocks.updateState.mockResolvedValue({ ...report, status: "potential" });
      const queryClient = new QueryClient({
        defaultOptions: { mutations: { retry: false } },
      });
      const { result } = renderHook(
        () => useInboxBulkActions([{ ...report, status }], report.id),
        { wrapper: createWrapper(queryClient) },
      );

      expect(result.current.snoozeDisabledReason === null).toBe(canPause);
      expect(result.current.suppressDisabledReason === null).toBe(canArchive);
      await act(async () => {
        await expect(
          result.current.snoozeSelected({ reason: "already_fixed", note: "" }),
        ).resolves.toBe(canPause);
      });
      expect(mocks.updateState).toHaveBeenCalledTimes(canPause ? 1 : 0);
    },
  );

  it("blocks pausing a mixed selection that includes a waiting report", async () => {
    const waitingReport: SignalReport = {
      ...report,
      id: "report-2",
      status: "potential",
    };
    const queryClient = new QueryClient();
    const { result } = renderHook(
      () =>
        useInboxBulkActions(
          [report, waitingReport],
          [report.id, waitingReport.id],
        ),
      { wrapper: createWrapper(queryClient) },
    );

    expect(result.current.suppressDisabledReason).toBeNull();
    await expect(
      result.current.snoozeSelected({ reason: "already_fixed", note: "" }),
    ).resolves.toBe(false);
    expect(mocks.updateState).not.toHaveBeenCalled();
  });

  it.each([
    ["suppressSelected", "suppressed", "other"],
    ["snoozeSelected", "potential", "already_fixed"],
  ] as const)(
    "%s updates the report before the request finishes",
    async (actionName, status, reason) => {
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
        void result.current[actionName]({ reason, note: "" });
      });

      await waitFor(() =>
        expect(
          queryClient.getQueryData<SignalReport>(
            inboxReportDetailQueryKey(report.id),
          ),
        ).toEqual(
          expect.objectContaining({
            status,
            dismissal_reason: reason,
            dismissal_note: null,
          }),
        ),
      );
    },
  );

  it.each([
    ["suppressSelected", "other"],
    ["snoozeSelected", "already_fixed"],
  ] as const)(
    "%s restores the report and reports a failed request",
    async (actionName, reason) => {
      mocks.updateState.mockRejectedValue(new Error("Request failed"));
      const queryClient = new QueryClient({
        defaultOptions: { mutations: { retry: false } },
      });
      queryClient.setQueryData(inboxReportDetailQueryKey(report.id), report);
      const { result } = renderHook(
        () => useInboxBulkActions([report], report.id),
        { wrapper: createWrapper(queryClient) },
      );

      await expect(
        result.current[actionName]({ reason, note: "" }),
      ).resolves.toBe(false);
      expect(
        queryClient.getQueryData(inboxReportDetailQueryKey(report.id)),
      ).toEqual(report);
      expect(mocks.success).not.toHaveBeenCalled();
      expect(mocks.error).toHaveBeenCalledWith(
        expect.stringContaining("1 failed"),
      );
    },
  );
});
