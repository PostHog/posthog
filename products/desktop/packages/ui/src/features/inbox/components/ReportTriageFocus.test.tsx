import type { SignalReport } from "@posthog/shared/types";
import { useReportChatPanelStore } from "@posthog/ui/features/inbox/stores/reportChatPanelStore";
import { navigateToInboxReportDetail } from "@posthog/ui/router/navigationBridge";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createEvent, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ReportTriageFocus } from "./ReportTriageFocus";

vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => null,
}));

vi.mock("@tanstack/react-router", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@tanstack/react-router")>()),
  useRouter: () => ({ preloadRoute: vi.fn() }),
}));

vi.mock("@posthog/ui/router/navigationBridge", () => ({
  navigateToInboxReportDetail: vi.fn(),
}));

vi.mock("@posthog/ui/shell/analytics", () => ({ track: vi.fn() }));

vi.mock("@posthog/ui/features/inbox/components/ReportVerdictBanner", () => ({
  ReportVerdictBanner: () => null,
}));

const summaryDetail = "The summary contains the evidence for this report.";

function renderTriage(): { onExit: ReturnType<typeof vi.fn> } {
  const timestamp = new Date().toISOString();
  const report: SignalReport = {
    id: "report-1",
    title: "Report one",
    summary: `A report headline.\n\n${summaryDetail}`,
    status: "ready",
    total_weight: 1,
    signal_count: 1,
    artefact_count: 0,
    created_at: timestamp,
    updated_at: timestamp,
  };
  const onExit = vi.fn();
  render(
    <QueryClientProvider client={new QueryClient()}>
      <ReportTriageFocus
        reports={[report]}
        allReports={[report]}
        scope="entire-project"
        hasActiveFilters={false}
        onExit={onExit}
      />
      <a href="https://example.com">Related page</a>
    </QueryClientProvider>,
  );
  return { onExit };
}

describe("ReportTriageFocus", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useReportChatPanelStore.setState({ open: false });
  });

  it.each(["s", "S"])("shows and hides the summary with %s", (key) => {
    renderTriage();
    expect(screen.queryByText(summaryDetail)).not.toBeInTheDocument();
    expect(screen.getByText("Read summary")).toBeInTheDocument();

    fireEvent.keyDown(window, { key });
    expect(screen.getByText(summaryDetail)).toBeVisible();
    expect(screen.getByText("Hide summary")).toBeInTheDocument();

    fireEvent.keyDown(window, { key });
    expect(screen.queryByText(summaryDetail)).not.toBeInTheDocument();
    expect(screen.getByText("Read summary")).toBeInTheDocument();
  });

  it.each([
    { label: "Enter on the page", key: "Enter", target: "page" },
    { label: "Enter on a button", key: "Enter", target: "button" },
    { label: "Enter on a link", key: "Enter", target: "link" },
    { label: "Command+Enter", key: "Enter", metaKey: true, target: "page" },
    { label: "Control+Enter", key: "Enter", ctrlKey: true, target: "page" },
    { label: "Command+S", key: "s", metaKey: true, target: "page" },
    { label: "Control+S", key: "s", ctrlKey: true, target: "page" },
    { label: "Alt+S", key: "s", altKey: true, target: "page" },
  ])("does not intercept $label", ({ target, label: _label, ...keys }) => {
    const { onExit } = renderTriage();
    const element =
      target === "button"
        ? screen.getByText("Exit triage")
        : target === "link"
          ? screen.getByText("Related page")
          : document.body;
    element.focus();

    for (const expanded of [false, true]) {
      const event = createEvent.keyDown(element, keys);
      fireEvent(element, event);

      expect(event.defaultPrevented).toBe(false);
      if (expanded) {
        expect(screen.getByText(summaryDetail)).toBeVisible();
        expect(screen.getByText("Hide summary")).toBeInTheDocument();
      } else {
        expect(screen.queryByText(summaryDetail)).not.toBeInTheDocument();
        expect(screen.getByText("Read summary")).toBeInTheDocument();
        fireEvent.keyDown(window, { key: "s" });
      }
      expect(onExit).not.toHaveBeenCalled();
      expect(navigateToInboxReportDetail).not.toHaveBeenCalled();
    }
  });
});
