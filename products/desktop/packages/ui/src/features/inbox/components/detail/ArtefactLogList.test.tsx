import type { AnySignalReportArtefact } from "@posthog/shared/types";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@tanstack/react-router", () => ({
  Link: ({
    to,
    params,
    children,
  }: {
    to: string;
    params: { reportId: string };
    children: React.ReactNode;
  }) => <a href={to.replace("$reportId", params.reportId)}>{children}</a>,
}));

import { ArtefactLogList } from "./ArtefactLogList";

function reportLink(
  content: Record<string, unknown>,
): AnySignalReportArtefact[] {
  return [
    {
      id: "a1",
      type: "report_link",
      created_at: "2026-01-01T00:00:00Z",
      content,
    } as AnySignalReportArtefact,
  ];
}

describe("ArtefactLogList", () => {
  it("shows the relation, the reason and a link to the related report", () => {
    render(
      <ArtefactLogList
        reportId="r1"
        artefacts={reportLink({
          kind: "depends_on",
          report_id: "r2",
          reason: "Needs the schema first",
        })}
      />,
    );

    expect(screen.getByText("Report linked")).toBeTruthy();
    expect(screen.getByText("Depends on")).toBeTruthy();
    expect(screen.getByText("Needs the schema first")).toBeTruthy();
    expect(screen.getByRole("link").getAttribute("href")).toBe("/reports/r2");
  });

  it("humanizes a link kind this client does not know", () => {
    render(
      <ArtefactLogList
        reportId="r1"
        artefacts={reportLink({ kind: "blocked_by", report_id: "r2" })}
      />,
    );

    expect(screen.getByText("Blocked by")).toBeTruthy();
  });
});
