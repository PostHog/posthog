import type { SignalReport } from "@posthog/shared/types";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DismissReportDialog } from "./DismissReportDialog";

const connectedRepositories = ["posthog/posthog", "posthog/posthog-js"];

// Mirrors the real hook's cold-cache behavior: it yields repositories only while enabled
// (the query is gated off when disabled, so the list is empty). Capturing the enabled
// argument is what lets the test assert the fetch is driven by the reason, not the popover.
const useGithubRepositoriesSpy = vi.fn((_search: string, enabled: boolean) => ({
  repositories: enabled ? connectedRepositories : [],
  isPending: false,
  isFetchingMore: false,
  hasMore: false,
  loadMore: vi.fn(),
}));

vi.mock("@posthog/ui/features/integrations/useIntegrations", () => ({
  useIntegrations: vi.fn(),
  useGithubRepositories: (search: string, enabled: boolean) =>
    useGithubRepositoriesSpy(search, enabled),
}));

vi.mock("@posthog/ui/features/integrations/store", () => ({
  useIntegrationSelectors: () => ({ hasGithubIntegration: true }),
}));

const report = {
  id: "report-1",
  title: "Checkout errors",
  summary: "Errors increased.",
  status: "ready",
  total_weight: 1,
  signal_count: 1,
  created_at: "2026-08-28T00:00:00Z",
  updated_at: "2026-08-28T00:00:00Z",
  artefact_count: 0,
} satisfies SignalReport;

describe("DismissReportDialog", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("distinguishes a project-wide archive from a temporary pause", async () => {
    const user = userEvent.setup();
    render(
      <DismissReportDialog
        open
        onOpenChange={vi.fn()}
        report={report}
        isSubmitting={false}
        snoozeDisabledReason={null}
        onConfirm={vi.fn()}
      />,
    );

    expect(
      screen.getByText('Archive report "Checkout errors" for everyone?'),
    ).toBeInTheDocument();
    expect(screen.getByText(/archives the report for everyone/)).toBeTruthy();

    await user.click(screen.getByLabelText("Already fixed"));

    expect(
      screen.getByText('Pause report "Checkout errors"?'),
    ).toBeInTheDocument();
    expect(screen.getByText(/pauses the report for everyone/)).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Pause for everyone" }),
    ).toBeInTheDocument();
  });

  it("offers an openable repository picker on a cold cache once wrong-repo is chosen", () => {
    render(
      <DismissReportDialog
        open
        onOpenChange={vi.fn()}
        report={report}
        isSubmitting={false}
        snoozeDisabledReason={null}
        onConfirm={vi.fn()}
      />,
    );

    const wrongRepoRadio = screen
      .getByText("Agent picked the wrong repository")
      .closest("div")
      ?.querySelector("#dismiss-report-dialog-reason-wrong_repo");
    if (!wrongRepoRadio) {
      throw new Error("Expected the wrong-repo reason radio to render");
    }
    fireEvent.click(wrongRepoRadio);

    // The repositories load on the reason alone, so with the picker still closed it renders
    // its openable trigger, not the dead-end disabled "No GitHub repos" button that a
    // fetch gated on the popover state would leave the reviewer stuck on.
    expect(screen.getByText("Search repositories")).toBeInTheDocument();
    expect(screen.queryByText("No GitHub repos")).not.toBeInTheDocument();
    expect(useGithubRepositoriesSpy).toHaveBeenLastCalledWith("", true);
  });
});
