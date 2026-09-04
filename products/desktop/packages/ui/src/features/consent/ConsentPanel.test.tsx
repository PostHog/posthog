import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { acceptBetaTerms, approveAiDataProcessing, track, writeText } =
  vi.hoisted(() => ({
    acceptBetaTerms: vi.fn(),
    approveAiDataProcessing: vi.fn(),
    track: vi.fn(),
    writeText: vi.fn(),
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

vi.mock("@posthog/ui/shell/analytics", () => ({ track }));

import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { ConsentPanel } from "./ConsentPanel";

function renderPanel(
  needsAiConsent: boolean,
  needsBetaTerms: boolean,
  isAdmin = true,
  requirements?: {
    needsAiConsent: boolean;
    needsBetaTerms: boolean;
  },
  retry = vi.fn().mockResolvedValue(undefined),
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
          retry,
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
    track.mockReset();
    writeText.mockReset();
    writeText.mockResolvedValue(undefined);
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

  it("gives members admin links and a refresh action", async () => {
    const retry = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    renderPanel(true, true, false, undefined, retry);

    expect(screen.queryByText("Accept beta terms")).not.toBeInTheDocument();
    const copyButtons = screen.getAllByRole("button", { name: "Copy link" });

    await user.click(copyButtons[0]);
    await user.click(copyButtons[1]);

    await waitFor(() =>
      expect(writeText).toHaveBeenNthCalledWith(
        1,
        "https://app.posthog.com/settings/organization-details#organization-ai-consent",
      ),
    );
    expect(writeText).toHaveBeenNthCalledWith(
      2,
      "https://app.posthog.com/settings/organization-details#organization-desktop-beta-terms",
    );
    expect(track).toHaveBeenNthCalledWith(
      1,
      ANALYTICS_EVENTS.CONSENT_ADMIN_LINK_COPIED,
      { consent_type: "ai", success: true },
    );
    expect(track).toHaveBeenNthCalledWith(
      2,
      ANALYTICS_EVENTS.CONSENT_ADMIN_LINK_COPIED,
      { consent_type: "desktop_beta_terms", success: true },
    );

    await user.click(screen.getByRole("button", { name: "Refresh" }));
    expect(retry).toHaveBeenCalledOnce();
  });
});
