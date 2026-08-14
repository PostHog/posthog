import { Theme } from "@radix-ui/themes";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Hoisted so the spies are initialized before the hoisted vi.mock factories
// that reference them run.
const { approveAiDataProcessing, logoutMutate, openSettings } = vi.hoisted(
  () => ({
    approveAiDataProcessing: vi.fn(),
    logoutMutate: vi.fn(),
    openSettings: vi.fn(),
  }),
);

vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useAuthenticatedClient: () => ({ approveAiDataProcessing }),
}));

vi.mock("@posthog/ui/features/auth/useAuthMutations", () => ({
  useLogoutMutation: () => ({ mutate: logoutMutate }),
}));

vi.mock("@posthog/ui/features/auth/useCurrentUser", () => ({
  authKeys: { currentUsers: () => ["auth", "current-user"] },
}));

vi.mock("@posthog/ui/features/settings/SettingsDialog", () => ({
  SettingsDialog: () => null,
  openSettingsDialog: openSettings,
}));

vi.mock("@posthog/ui/shell/analytics", () => ({ track: vi.fn() }));

import { AiApprovalScreen } from "./AiApprovalScreen";

function renderInTheme(isAdmin: boolean) {
  const queryClient = new QueryClient({
    defaultOptions: { mutations: { retry: false }, queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <Theme>
        <AiApprovalScreen orgName="Acme" isAdmin={isAdmin} />
      </Theme>
    </QueryClientProvider>,
  );
}

describe("AiApprovalScreen", () => {
  beforeEach(() => {
    approveAiDataProcessing.mockReset();
    logoutMutate.mockReset();
    openSettings.mockReset();
  });

  it("calls approveAiDataProcessing once when the admin clicks the button", async () => {
    approveAiDataProcessing.mockResolvedValueOnce(undefined);
    const user = userEvent.setup();

    renderInTheme(true);

    const button = screen.getByRole("button", {
      name: /Approve AI data processing/i,
    });
    await user.click(button);

    await waitFor(() =>
      expect(approveAiDataProcessing).toHaveBeenCalledExactlyOnceWith(),
    );
  });

  it("renders the ask-admin copy and no approve button for non-admin users", () => {
    renderInTheme(false);

    expect(
      screen.getByText(
        /Ask an organization admin to approve AI data processing/i,
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Approve AI data processing/i }),
    ).not.toBeInTheDocument();
  });

  it("shows an error callout when the approval request rejects", async () => {
    approveAiDataProcessing.mockRejectedValueOnce(new Error("forbidden"));
    const user = userEvent.setup();

    renderInTheme(true);

    await user.click(
      screen.getByRole("button", { name: /Approve AI data processing/i }),
    );

    expect(
      await screen.findByText(/Could not approve AI data processing/i),
    ).toBeInTheDocument();
  });
});
