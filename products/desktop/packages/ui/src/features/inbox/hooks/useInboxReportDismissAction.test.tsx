import type { SignalReport } from "@posthog/shared/types";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  updateState: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
  track: vi.fn(),
}));

vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => ({
    updateSignalReportState: mocks.updateState,
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
  toast: { success: mocks.toastSuccess, error: mocks.toastError },
}));

vi.mock("@posthog/ui/shell/analytics", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@posthog/ui/shell/analytics")>();
  return { ...actual, track: mocks.track };
});

import { useInboxReportDismissAction } from "./useInboxReportDismissAction";

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

const wrapper = ({ children }: { children: ReactNode }): React.JSX.Element => (
  <QueryClientProvider
    client={
      new QueryClient({
        defaultOptions: {
          queries: { retry: false },
          mutations: { retry: false },
        },
      })
    }
  >
    {children}
  </QueryClientProvider>
);

function DismissActionHarness(): React.JSX.Element {
  const { dialog, openDialog } = useInboxReportDismissAction(report);
  return (
    <>
      <button type="button" onClick={() => openDialog()}>
        Open dismiss
      </button>
      {dialog}
    </>
  );
}

describe("useInboxReportDismissAction", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("keeps the dialog and the typed note when the request fails", async () => {
    mocks.updateState.mockRejectedValue(new Error("Request failed"));
    const user = userEvent.setup();
    render(<DismissActionHarness />, { wrapper });

    await user.click(screen.getByText("Open dismiss"));
    await user.click(
      screen.getByRole("radio", { name: /Agent's analysis is wrong/ }),
    );
    await user.type(
      screen.getByPlaceholderText("Optional: add detail"),
      "The stack trace is from a different service",
    );
    await user.click(screen.getByText("Dismiss report"));

    await waitFor(() => expect(mocks.toastError).toHaveBeenCalled());
    expect(screen.getByPlaceholderText("Optional: add detail")).toHaveValue(
      "The stack trace is from a different service",
    );
  });

  it("closes the dialog once the dismissal lands", async () => {
    mocks.updateState.mockResolvedValue({ ...report, status: "suppressed" });
    const user = userEvent.setup();
    render(<DismissActionHarness />, { wrapper });

    await user.click(screen.getByText("Open dismiss"));
    await user.click(
      screen.getByRole("radio", { name: /Agent's analysis is wrong/ }),
    );
    await user.click(screen.getByText("Dismiss report"));

    await waitFor(() =>
      expect(
        screen.queryByPlaceholderText("Optional: add detail"),
      ).not.toBeInTheDocument(),
    );
  });
});
