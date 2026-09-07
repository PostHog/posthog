import type { SignalReport } from "@posthog/shared/types";
import { useInboxReportActionDraftStore } from "@posthog/ui/features/inbox/stores/inboxReportActionDraftStore";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
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

function createWrapper(queryClient = new QueryClient()) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
  };
}

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

async function enterDismissal(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByText("Open dismiss"));
  await user.click(
    screen.getByRole("radio", { name: /Agent's analysis is wrong/ }),
  );
  await user.type(
    screen.getByPlaceholderText("Optional: add detail"),
    "Retain this note",
  );
  await user.click(screen.getByText("Dismiss report"));
}

describe("useInboxReportDismissAction", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useInboxReportActionDraftStore.setState({
      generation: 0,
      dismiss: {},
      resolve: {},
    });
  });

  it("reopens a failed dismissal with its typed note", async () => {
    mocks.updateState.mockRejectedValue(new Error("Request failed"));
    const user = userEvent.setup();
    render(<DismissActionHarness />, { wrapper: createWrapper() });

    await enterDismissal(user);

    await waitFor(() => expect(mocks.toastError).toHaveBeenCalled());
    expect(screen.getByPlaceholderText("Optional: add detail")).toHaveValue(
      "Retain this note",
    );
  });

  it("keeps the dialog closed once the dismissal lands", async () => {
    mocks.updateState.mockResolvedValue({ ...report, status: "suppressed" });
    const user = userEvent.setup();
    render(<DismissActionHarness />, { wrapper: createWrapper() });

    await enterDismissal(user);

    await waitFor(() => expect(mocks.updateState).toHaveBeenCalled());
    expect(
      screen.queryByPlaceholderText("Optional: add detail"),
    ).not.toBeInTheDocument();
  });

  it("restores retry input after the action screen unmounts", async () => {
    const user = userEvent.setup();
    let rejectRequest: ((error: Error) => void) | undefined;
    mocks.updateState.mockReturnValue(
      new Promise<SignalReport>((_resolve, reject) => {
        rejectRequest = reject;
      }),
    );
    const queryClient = new QueryClient({
      defaultOptions: { mutations: { retry: false } },
    });
    const firstRender = render(<DismissActionHarness />, {
      wrapper: createWrapper(queryClient),
    });

    await enterDismissal(user);
    await waitFor(() => expect(mocks.updateState).toHaveBeenCalled());
    firstRender.unmount();
    await act(async () => rejectRequest?.(new Error("Request failed")));

    render(<DismissActionHarness />, { wrapper: createWrapper(queryClient) });

    expect(
      await screen.findByRole("radio", {
        name: /Agent's analysis is wrong/,
      }),
    ).toBeChecked();
    expect(screen.getByPlaceholderText("Optional: add detail")).toHaveValue(
      "Retain this note",
    );
  });
});
