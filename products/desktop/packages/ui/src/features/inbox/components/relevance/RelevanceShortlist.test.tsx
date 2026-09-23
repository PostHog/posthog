import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { RelevanceShortlist } from "./RelevanceShortlist";

const props = {
  reports: [],
  loading: false,
  failed: false,
  saving: false,
  lastSnoozed: null,
  onRetry: vi.fn(),
  onShowQueue: vi.fn(),
  onSnooze: vi.fn(),
};
describe("Relevance shortlist", () => {
  it("keeps the wider queue accessible after a failure", () => {
    render(<RelevanceShortlist {...props} failed />);
    expect(screen.queryByText(/Nothing needs/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(props.onRetry).toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Browse all reports" }));
    expect(props.onShowQueue).toHaveBeenCalled();
  });
  it("does not call a loading shortlist empty", () => {
    render(<RelevanceShortlist {...props} loading />);
    expect(screen.queryByText(/Nothing needs/)).toBeNull();
  });
});
