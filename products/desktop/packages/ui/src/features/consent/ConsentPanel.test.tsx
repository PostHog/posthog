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
  requirements?: {
    needsAiConsent: boolean;
    needsBetaTerms: boolean;
  },
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
        requirements={requirements}
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

    expect(
      screen.queryByRole("button", { name: "Approve AI data processing" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("PostHog Desktop beta terms")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Accept beta terms" }));

    await waitFor(() =>
      expect(acceptBetaTerms).toHaveBeenCalledExactlyOnceWith("org-id"),
    );
    expect(approveAiDataProcessing).not.toHaveBeenCalled();
  });

  it("presents separate actions and keeps legal detail optional", async () => {
    const user = userEvent.setup();
    renderPanel(true, true);

    expect(
      screen.getByRole("button", { name: "Approve AI data processing" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Accept beta terms" }),
    ).toBeInTheDocument();
    const details = screen.getAllByRole("button", { name: "Details" });
    expect(details[0]).toHaveAttribute("aria-expanded", "false");
    await user.click(details[0]);
    expect(details[0]).toHaveAttribute("aria-expanded", "true");
  });

  it("keeps each decision visible and marks it accepted", () => {
    renderPanel(false, false, true, {
      needsAiConsent: true,
      needsBetaTerms: true,
    });

    expect(screen.getAllByRole("button", { name: "Accepted" })).toHaveLength(2);
  });

  it("keeps one failed decision recoverable without retrying the other", async () => {
    approveAiDataProcessing.mockResolvedValue(undefined);
    acceptBetaTerms.mockRejectedValue(new Error("reauth required"));
    const user = userEvent.setup();
    renderPanel(true, true);

    await user.click(
      screen.getByRole("button", { name: "Approve AI data processing" }),
    );
    await user.click(screen.getByRole("button", { name: "Accept beta terms" }));

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(approveAiDataProcessing).toHaveBeenCalledExactlyOnceWith("org-id");
    expect(acceptBetaTerms).toHaveBeenCalledExactlyOnceWith("org-id");
  });

  it("asks members to contact an admin without rendering an accept button", () => {
    renderPanel(true, true, false);

    expect(screen.queryByText("Accept beta terms")).not.toBeInTheDocument();
  });
});
