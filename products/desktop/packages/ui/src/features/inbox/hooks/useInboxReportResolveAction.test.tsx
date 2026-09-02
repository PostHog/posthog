import type { SignalReport } from "@posthog/shared/types";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  updateState: vi.fn(),
  trackAction: vi.fn(),
  trackResult: vi.fn(),
  actionTrackerArgs: [] as unknown[],
  resultTrackerArgs: [] as unknown[],
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
}));

vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => ({
    updateSignalReportState: mocks.updateState,
  }),
}));

vi.mock("@posthog/ui/features/inbox/hooks/useReportActionTracker", () => ({
  useReportActionTracker: (...args: unknown[]) => {
    mocks.actionTrackerArgs = args;
    return mocks.trackAction;
  },
  useReportActionResultTracker: (...args: unknown[]) => {
    mocks.resultTrackerArgs = args;
    return mocks.trackResult;
  },
}));

vi.mock("@posthog/ui/primitives/toast", () => ({
  toast: { success: mocks.toastSuccess, error: mocks.toastError },
}));

import { useInboxReportResolveAction } from "./useInboxReportResolveAction";

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
};

function createWrapper(queryClient = new QueryClient()) {
  return function Wrapper({
    children,
  }: {
    children: ReactNode;
  }): React.JSX.Element {
    return (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
  };
}

const wrapper = createWrapper(
  new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  }),
);

describe("useInboxReportResolveAction", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("tracks triage outcomes and blocks overlapping resolve requests", async () => {
    let finishRequest: ((value: SignalReport) => void) | undefined;
    mocks.updateState.mockReturnValue(
      new Promise<SignalReport>((resolve) => {
        finishRequest = resolve;
      }),
    );
    const { result } = renderHook(
      () => useInboxReportResolveAction(report, "triage", "triage-1"),
      { wrapper },
    );

    act(() => {
      result.current.resolveWithReason("fixed_outside_posthog");
      result.current.resolveWithReason("fixed_outside_posthog");
    });

    await waitFor(() => expect(mocks.updateState).toHaveBeenCalledOnce());
    expect(mocks.actionTrackerArgs.slice(1)).toEqual(["triage", "triage-1"]);
    expect(mocks.resultTrackerArgs.slice(1)).toEqual(["triage", "triage-1"]);
    expect(mocks.trackAction).toHaveBeenCalledWith("resolve", {
      dismissal_reason: "fixed_outside_posthog",
    });

    await act(async () => finishRequest?.({ ...report, status: "resolved" }));
    await waitFor(() =>
      expect(mocks.trackResult).toHaveBeenCalledWith(
        "resolve",
        "succeeded",
        expect.any(Number),
      ),
    );
  });

  it("updates the list before the request finishes without a success toast", async () => {
    let finishRequest: ((value: SignalReport) => void) | undefined;
    mocks.updateState.mockReturnValue(
      new Promise<SignalReport>((resolve) => {
        finishRequest = resolve;
      }),
    );
    const queryClient = new QueryClient();
    const listKey = [
      "inbox",
      "signal-reports",
      "list",
      { status: "ready" },
    ] as const;
    queryClient.setQueryData(listKey, { results: [report], count: 1 });
    const invalidate = vi
      .spyOn(queryClient, "invalidateQueries")
      .mockReturnValue(new Promise<void>(() => {}));
    const { result } = renderHook(() => useInboxReportResolveAction(report), {
      wrapper: createWrapper(queryClient),
    });

    act(() => result.current.resolveWithReason("fixed_outside_posthog"));
    await waitFor(() => expect(mocks.updateState).toHaveBeenCalledOnce());
    expect(queryClient.getQueryData(listKey)).toEqual({
      results: [],
      count: 0,
    });
    await act(async () => finishRequest?.({ ...report, status: "resolved" }));

    expect(mocks.toastSuccess).not.toHaveBeenCalled();
    expect(invalidate).toHaveBeenCalled();
  });

  it("restores the list when the request fails", async () => {
    mocks.updateState.mockRejectedValue(new Error("Request failed"));
    const queryClient = new QueryClient({
      defaultOptions: { mutations: { retry: false } },
    });
    const listKey = [
      "inbox",
      "signal-reports",
      "list",
      { status: "ready" },
    ] as const;
    queryClient.setQueryData(listKey, { results: [report], count: 1 });
    const { result } = renderHook(() => useInboxReportResolveAction(report), {
      wrapper: createWrapper(queryClient),
    });

    act(() => result.current.resolveWithReason("fixed_outside_posthog"));

    await waitFor(() =>
      expect(queryClient.getQueryData(listKey)).toEqual({
        results: [report],
        count: 1,
      }),
    );
    expect(mocks.toastError).toHaveBeenCalledWith("Request failed");
  });
});
