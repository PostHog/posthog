import type {
  AutostartSkipArtefact,
  AutostartSkipContent,
} from "@posthog/shared/types";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const openReport = vi.fn();
vi.mock("@posthog/ui/features/inbox/hooks/useOpenInboxReport", () => ({
  useOpenInboxReport: () => openReport,
}));

import { ArtefactLogList } from "./ArtefactLogList";

function autostartSkip(content: AutostartSkipContent): AutostartSkipArtefact {
  return {
    id: "skip-1",
    type: "autostart_skip",
    created_at: "2026-06-01T00:00:00Z",
    content,
  };
}

describe("ArtefactLogList", () => {
  beforeEach(() => {
    openReport.mockReset();
  });

  it.each([
    ["duplicate_of", "Duplicate"],
    ["blocked_by_dependency", "Waiting on a dependency"],
    ["plan_parent", "Tracked by other reports"],
  ] as const)(
    "explains an autostart skip for %s",
    (skipReason, reasonLabel) => {
      render(
        <ArtefactLogList
          reportId="report-1"
          artefacts={[
            autostartSkip({
              skip_reason: skipReason,
              linked_report_id: null,
              detail: "Work starts when the other report closes.",
            }),
          ]}
        />,
      );

      expect(screen.getByText("Work not started")).toBeTruthy();
      expect(screen.getByText(reasonLabel)).toBeTruthy();
      expect(
        screen.getByText("Work starts when the other report closes."),
      ).toBeTruthy();
      expect(screen.queryByText("No preview available.")).toBeNull();
      expect(screen.queryByText("Open related report")).toBeNull();
    },
  );

  it("opens the linked report in the app", () => {
    render(
      <ArtefactLogList
        reportId="report-1"
        artefacts={[
          autostartSkip({
            skip_reason: "duplicate_of",
            linked_report_id: "report-2",
            detail: "This report duplicates another open report.",
          }),
        ]}
      />,
    );

    fireEvent.click(screen.getByText("Open related report"));

    expect(openReport).toHaveBeenCalledWith("report-2");
  });
});
