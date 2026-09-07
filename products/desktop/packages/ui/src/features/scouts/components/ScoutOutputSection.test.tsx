import type { ScoutRun } from "@posthog/api-client/posthog-client";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  openReport: vi.fn().mockResolvedValue(undefined),
  emissions: vi.fn(),
  reports: vi.fn(),
}));
vi.mock("@posthog/ui/features/inbox/hooks/useOpenInboxReport", () => ({
  useOpenInboxReport: () => mocks.openReport,
}));
vi.mock("@posthog/ui/features/inbox/hooks/useInboxReports", () => ({
  useInboxReportById: (id: string) => ({
    data: {
      title:
        id === "report-created" ? "Check checkout errors" : "Review slow pages",
      summary: "A short report summary.",
      priority: "P2",
    },
    isLoading: false,
    isError: false,
  }),
}));
vi.mock("framer-motion", () => ({ useInView: () => true }));
vi.mock("@posthog/ui/shell/analytics", () => ({ track: vi.fn() }));
vi.mock("../hooks/useScoutRunEmissions", () => ({
  useScoutRunEmissions: mocks.emissions,
}));
vi.mock("../hooks/useScoutEmissionReports", () => ({
  useScoutEmissionReports: mocks.reports,
}));
vi.mock("@posthog/ui/primitives/RelativeTimestamp", () => ({
  RelativeTimestamp: () => <span>Run time</span>,
}));
vi.mock("@posthog/ui/features/editor/components/MarkdownRenderer", () => ({
  MarkdownRenderer: ({ content }: { content: string }) => <p>{content}</p>,
}));
vi.mock("./ScoutFindingDiscussButton", () => ({
  ScoutFindingDiscussButton: () => null,
}));
vi.mock("./ScoutFindingShareButton", () => ({
  ScoutFindingShareButton: () => null,
}));

import { ScoutOutputSection } from "./ScoutOutputSection";

describe("ScoutOutputSection", () => {
  afterEach(() => vi.restoreAllMocks());
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.emissions.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
    });
    mocks.reports.mockReturnValue({ data: undefined });
  });

  it("expands a shared finding and lets the user collapse it", () => {
    const run: ScoutRun = {
      run_id: "run-example",
      skill_name: "signals-scout-example",
      skill_version: 1,
      status: "completed",
      started_at: null,
      completed_at: null,
      task_id: null,
      task_run_id: null,
      task_url: "https://example.com/run",
      summary: "",
      emitted_count: 1,
      emitted_finding_ids: ["finding-example"],
    };
    mocks.emissions.mockReturnValue({
      data: [
        {
          id: "finding-example",
          finding_id: "finding-example",
          weight: 1,
          run_id: run.run_id,
          source_id: "source-example",
          description: "A sample finding.",
          confidence: 1,
          severity: null,
          emitted_at: "2026-01-01T00:00:00Z",
        },
      ],
      isLoading: false,
      isError: false,
    });
    const scrollIntoView = vi
      .spyOn(Element.prototype, "scrollIntoView")
      .mockImplementation(() => {});
    const { rerender } = render(
      <ScoutOutputSection runs={[run]} loading={false} />,
    );
    const toggle = screen.getByRole("button", { name: /confidence/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("link", { name: "Open task run" })).toBeNull();

    rerender(
      <ScoutOutputSection
        runs={[run]}
        loading={false}
        highlightFindingId="finding-example"
      />,
    );
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("link", { name: "Open task run" })).toHaveAttribute(
      "href",
      run.task_url,
    );
    expect(scrollIntoView).toHaveBeenCalled();

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
  });

  it.each([0, 1])(
    "opens reports when the old signal count is %s and emissions are unavailable",
    async (emittedCount) => {
      const run: ScoutRun = {
        run_id: "run-example",
        skill_name: "signals-scout-example",
        skill_version: 1,
        status: "completed",
        started_at: null,
        completed_at: null,
        task_id: null,
        task_run_id: null,
        task_url: null,
        summary: "",
        emitted_count: emittedCount,
        emitted_finding_ids: [],
        emitted_report_ids: ["report-created", "report-created"],
        edited_report_ids: ["report-created", "report-updated"],
      };

      render(<ScoutOutputSection runs={[run]} loading={false} />);

      expect(screen.queryByText(/No output/)).toBeNull();
      const created = screen.getByRole("button", {
        name: /Check checkout errors/,
      });
      const updated = screen.getByRole("button", { name: /Review slow pages/ });
      expect(screen.getAllByText("A short report summary.")).toHaveLength(2);
      fireEvent.click(created);
      await waitFor(() => expect(created).not.toBeDisabled());
      expect(mocks.openReport).toHaveBeenLastCalledWith("report-created");
      fireEvent.click(updated);
      await waitFor(() => expect(updated).not.toBeDisabled());
      expect(mocks.openReport).toHaveBeenLastCalledWith("report-updated");
      expect(mocks.emissions).toHaveBeenCalledWith(
        emittedCount ? ["run-example"] : [],
      );
    },
  );
});
