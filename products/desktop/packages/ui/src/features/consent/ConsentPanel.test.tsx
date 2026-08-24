import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { acceptBetaTerms, approveAiDataProcessing } = vi.hoisted(() => ({
  acceptBetaTerms: vi.fn(),
  approveAiDataProcessing: vi.fn(),
}));

vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useAuthenticatedClient: () => ({
    acceptDesktopBetaTerms: acceptBetaTerms,
    approveAiDataProcessing,
  }),
}));

vi.mock("@posthog/ui/features/auth/useCurrentUser", () => ({
  authKeys: { currentUsers: () => ["auth", "current-user"] },
  useCurrentUser: () => ({
    data: { organization: { id: "org-id", name: "Example Org" } },
  }),
}));

vi.mock("@posthog/ui/shell/analytics", () => ({ track: vi.fn() }));

import { ConsentPanel } from "./ConsentPanel";

function renderPanel(
  needsAiConsent: boolean,
  needsBetaTerms: boolean,
  isAdmin = true,
) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ConsentPanel
        consent={{
          status: "resolved",
          organizationId: "org-id",
          needsAiConsent,
          needsBetaTerms,
          satisfied: !needsAiConsent && !needsBetaTerms,
        }}
        isAdmin={isAdmin}
      />
    </QueryClientProvider>,
  );
}

describe("ConsentPanel", () => {
  beforeEach(() => {
    acceptBetaTerms.mockReset();
    approveAiDataProcessing.mockReset();
  });

  it("shows and accepts only the outstanding beta terms", async () => {
    acceptBetaTerms.mockResolvedValue(undefined);
    const user = userEvent.setup();
    renderPanel(false, true);

    expect(screen.queryByText("AI data processing")).not.toBeInTheDocument();
    expect(screen.getByText("PostHog Desktop beta terms")).toBeInTheDocument();
    await user.click(screen.getByText("Accept and continue"));

    await waitFor(() =>
      expect(acceptBetaTerms).toHaveBeenCalledExactlyOnceWith("org-id"),
    );
    expect(approveAiDataProcessing).not.toHaveBeenCalled();
  });

  it("shows completion after the requirements are accepted", () => {
    renderPanel(false, false);

    expect(
      screen.getByText("Organization consent complete"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Accept and continue" }),
    ).not.toBeInTheDocument();
  });

  it("keeps partial failure recoverable after addressing both writes", async () => {
    approveAiDataProcessing.mockResolvedValue(undefined);
    acceptBetaTerms.mockRejectedValue(new Error("reauth required"));
    const user = userEvent.setup();
    renderPanel(true, true);

    await user.click(screen.getByText("Accept and continue"));

    expect(
      await screen.findByText(/Some organization consent updates/),
    ).toBeInTheDocument();
    expect(approveAiDataProcessing).toHaveBeenCalledExactlyOnceWith("org-id");
    expect(acceptBetaTerms).toHaveBeenCalledExactlyOnceWith("org-id");
  });

  it("asks members to contact an admin without rendering an accept button", () => {
    renderPanel(true, true, false);

    expect(
      screen.getByText("Ask an organization admin to accept these terms."),
    ).toBeInTheDocument();
    expect(screen.queryByText("Accept and continue")).not.toBeInTheDocument();
  });
});
