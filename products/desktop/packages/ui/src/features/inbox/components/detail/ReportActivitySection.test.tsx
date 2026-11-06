import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@posthog/ui/features/inbox/hooks/useInboxReports", () => ({
  useInboxReportArtefacts: () => ({ data: { results: [] } }),
}));
vi.mock("./ArtefactLogList", () => ({ ArtefactLogList: () => null }));

import { ReportActivitySection } from "./ReportActivitySection";

describe("ReportActivitySection", () => {
  it.each([1, 3])(
    "shows %i collapsed confirmations without visible artefacts",
    (count) => {
      render(
        <ReportActivitySection
          reportId="report-1"
          collapsedNoteCount={count}
        />,
      );
      fireEvent.click(screen.getByText("Activity"));
      expect(
        screen.getByText(
          `Corroborated ${count} more ${count === 1 ? "time" : "times"} by a scout, with nothing new to add.`,
        ),
      ).toBeTruthy();
    },
  );

  it("hides an activity section with no entries or confirmations", () => {
    const { container } = render(<ReportActivitySection reportId="report-1" />);
    expect(container.firstChild).toBeNull();
  });
});
