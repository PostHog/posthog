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
  it("renders the citation label inline", () => {
    renderInTheme(
      <EvidenceRefChip target={{ kind: "insight", id: "9pQx3" }}>
        Checkout funnel
      </EvidenceRefChip>,
    );
    expect(
      screen.getByRole("button", { name: "Checkout funnel" }),
    ).toBeDefined();
  });

  it("opens the PostHog url on click when the link carries one", () => {
    const url = "https://us.posthog.com/project/2/insights/9pQx3";
    renderInTheme(
      <EvidenceRefChip target={{ kind: "insight", id: "9pQx3", url }}>
        Checkout funnel
      </EvidenceRefChip>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Checkout funnel" }));
    expect(openExternalUrl).toHaveBeenCalledWith(url);
  });

  it("does nothing on click without a url", () => {
    vi.mocked(openExternalUrl).mockClear();
    renderInTheme(
      <EvidenceRefChip target={{ kind: "error", id: "018f" }}>
        TypeError spike
      </EvidenceRefChip>,
    );
    fireEvent.click(screen.getByRole("button", { name: "TypeError spike" }));
    expect(openExternalUrl).not.toHaveBeenCalled();
  });

  it("renders from an evidence: markdown link in agent output", () => {
    // Guards the whole path: url transform must keep the scheme and the `a`
    // component must dispatch to the chip instead of an external link.
    renderInTheme(
      <MarkdownRenderer content="The [coupon funnel](evidence:insight/9pQx3) dropped." />,
    );
    expect(screen.getByRole("button", { name: "coupon funnel" })).toBeDefined();
    expect(screen.queryByRole("link", { name: /coupon funnel/ })).toBeNull();
  });
});
