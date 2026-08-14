import { Theme } from "@radix-ui/themes";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("../../../shell/openExternal", () => ({
  openExternalUrl: vi.fn(),
}));

import { openExternalUrl } from "../../../shell/openExternal";
import { EvidenceRefChip } from "./EvidenceRefChip";
import { MarkdownRenderer } from "./MarkdownRenderer";

function renderInTheme(node: React.ReactNode) {
  return render(<Theme>{node}</Theme>);
}

describe("EvidenceRefChip", () => {
  it("renders a plain reference as text, not an interactive element", () => {
    renderInTheme(
      <EvidenceRefChip target={{ kind: "insight", id: "9pQx3" }}>
        Checkout funnel
      </EvidenceRefChip>,
    );
    expect(screen.getByText("Checkout funnel")).toBeDefined();
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("opens the PostHog url in the external browser when clicked", () => {
    const url = "https://us.posthog.com/project/2/insights/9pQx3";
    renderInTheme(
      <EvidenceRefChip target={{ kind: "insight", id: "9pQx3", url }}>
        Checkout funnel
      </EvidenceRefChip>,
    );
    const link = screen.getByRole("link", { name: "Checkout funnel" });
    fireEvent.click(link);
    expect(openExternalUrl).toHaveBeenCalledWith(url);
  });

  it("renders from an evidence: markdown link in agent output", () => {
    // Guards the whole path: url transform must keep the scheme and the `a`
    // component must dispatch to the chip instead of an external link.
    renderInTheme(
      <MarkdownRenderer content="The [coupon funnel](evidence:insight/9pQx3) dropped." />,
    );
    expect(screen.getByText("coupon funnel")).toBeDefined();
    // Without a url parameter the reference is not a link at all — a plain
    // external-link fallback would render one.
    expect(screen.queryByRole("link")).toBeNull();
  });
});
