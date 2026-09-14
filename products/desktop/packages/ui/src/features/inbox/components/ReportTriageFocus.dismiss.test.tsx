import { INBOX_SCOPE_ENTIRE_PROJECT } from "@posthog/core/inbox/reportMembership";
import type { SignalReport } from "@posthog/shared/types";
import { useInboxReportActionDraftStore } from "@posthog/ui/features/inbox/stores/inboxReportActionDraftStore";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  updateState: vi.fn(),
}));

vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => ({
    updateSignalReportState: mocks.updateState,
    getSignalReportArtefacts: vi.fn().mockResolvedValue({ results: [] }),
  }),
}));

vi.mock("@posthog/ui/features/auth/useCurrentUser", async (importOriginal) => {
  const actual =
    await importOriginal<
      typeof import("@posthog/ui/features/auth/useCurrentUser")
    >();
  return { ...actual, useCurrentUser: () => ({ data: { uuid: "me" } }) };
});

vi.mock("@posthog/ui/primitives/toast", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@posthog/ui/shell/analytics", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@posthog/ui/shell/analytics")>();
  return { ...actual, track: vi.fn() };
});

vi.mock("@posthog/ui/router/navigationBridge", () => ({
  navigateToInboxReportDetail: vi.fn(),
}));

vi.mock("@posthog/ui/router/useOpenTask", () => ({
  openTaskInput: vi.fn(),
  useOpenTask: () => vi.fn(),
}));

vi.mock("@posthog/ui/features/inbox/hooks/useCreatePrReport", () => ({
  useCreatePrReport: () => ({ createPrReport: vi.fn(), isCreatingPr: false }),
}));

vi.mock("@posthog/ui/features/inbox/hooks/useDiscussReport", () => ({
  useDiscussReport: () => ({ discussReport: vi.fn(), isDiscussing: false }),
}));

vi.mock("@posthog/ui/features/canvas/hooks/useTaskChannels", () => ({
  useTaskChannels: () => ({
    generalChannel: { id: "channel-1" },
    isLoading: false,
  }),
}));

vi.mock(
  "@posthog/ui/features/inbox/hooks/useInboxReportDetailPrefetch",
  () => ({
    useInboxReportDetailPrefetch: () => ({ prefetch: vi.fn() }),
  }),
);

import { ReportTriageFocus } from "./ReportTriageFocus";

const reports: SignalReport[] = [
  {
    id: "report-1",
    title: "First report",
    summary: "Summary",
    status: "ready",
    total_weight: 1,
    signal_count: 1,
    artefact_count: 0,
    created_at: "2026-08-20T09:00:00Z",
    updated_at: "2026-08-20T09:00:00Z",
  },
];

function createWrapper(queryClient = new QueryClient()) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
  };
}

describe("ReportTriageFocus dismiss", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useInboxReportActionDraftStore.setState({
      generation: 0,
      dismiss: {},
      resolve: {},
    });
  });

  // Triage is a keyboard flow, so the verdict must not hold the reader for the
  // length of the request. The dialog closes on confirm and the write runs
  // behind it.
  it("closes the dialog before the dismiss request settles", async () => {
    let settle: (updated: SignalReport) => void = () => {};
    mocks.updateState.mockReturnValue(
      new Promise<SignalReport>((resolve) => {
        settle = resolve;
      }),
    );
    const user = userEvent.setup();
    render(
      <ReportTriageFocus
        reports={reports}
        allReports={reports}
        scope={INBOX_SCOPE_ENTIRE_PROJECT}
        hasActiveFilters={false}
        onExit={vi.fn()}
      />,
      { wrapper: createWrapper() },
    );

    await user.keyboard("a");
    await screen.findByPlaceholderText("Optional: add detail");
    await user.click(
      screen.getByRole("radio", { name: /Agent's analysis is wrong/ }),
    );
    await user.click(screen.getByText("Dismiss report"));

    await waitFor(() => expect(mocks.updateState).toHaveBeenCalled());
    expect(
      screen.queryByPlaceholderText("Optional: add detail"),
    ).not.toBeInTheDocument();

    await act(async () => {
      settle({ ...reports[0], status: "suppressed" });
    });
  });
});
