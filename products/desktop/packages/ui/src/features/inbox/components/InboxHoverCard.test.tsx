import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  navigateToReport: vi.fn(),
}));

vi.mock("@posthog/quill", () => ({
  PopoverContent: ({ children }: { children: ReactNode }) => (
    <div>{children}</div>
  ),
}));
vi.mock("@posthog/ui/features/inbox/components/InboxPane", () => ({
  InboxPane: ({
    onReportActivate,
  }: {
    onReportActivate: (report: { id: string }) => void;
  }) => (
    <button type="button" onClick={() => onReportActivate({ id: "report-1" })}>
      Open report
    </button>
  ),
}));
vi.mock("@posthog/ui/router/navigationBridge", () => ({
  navigateToReport: mocks.navigateToReport,
}));

import { InboxHoverCard } from "./InboxHoverCard";

describe("InboxHoverCard", () => {
  beforeEach(() => vi.clearAllMocks());

  it("opens a report from Self-driving and closes the card", () => {
    const onClose = vi.fn();
    render(<InboxHoverCard onClose={onClose} />);

    fireEvent.click(screen.getByText("Open report"));

    expect(mocks.navigateToReport).toHaveBeenCalledWith("report-1", {
      sourceHref: "/inbox",
    });
    expect(onClose).toHaveBeenCalledOnce();
  });
});
