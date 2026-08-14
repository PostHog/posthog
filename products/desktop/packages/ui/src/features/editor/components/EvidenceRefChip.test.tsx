import { Theme } from "@radix-ui/themes";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../../../shell/openExternal", () => ({
  openExternalUrl: vi.fn(),
}));

import { openExternalUrl } from "../../../shell/openExternal";
import { ANONYMOUS_AUTH_STATE, useAuthStore } from "../../auth/store";
import { EvidenceHoverCard, EvidenceRefChip } from "./EvidenceRefChip";
import { MarkdownRenderer } from "./MarkdownRenderer";

function renderInTheme(node: React.ReactNode) {
  return render(<Theme>{node}</Theme>);
}

function signIn() {
  useAuthStore.setState({
    authState: {
      ...ANONYMOUS_AUTH_STATE,
      cloudRegion: "us",
      currentProjectId: 2,
    },
  });
}

afterEach(() => {
  useAuthStore.setState({ authState: ANONYMOUS_AUTH_STATE });
});

describe("EvidenceRefChip", () => {
  it("renders as plain text without a project to link into", () => {
    renderInTheme(
      <EvidenceRefChip target={{ kind: "insight", id: "9pQx3" }}>
        Checkout funnel
      </EvidenceRefChip>,
    );
    expect(screen.getByText("Checkout funnel")).toBeDefined();
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("derives the PostHog url from the reference and opens it externally", () => {
    signIn();
    renderInTheme(
      <EvidenceRefChip target={{ kind: "insight", id: "9pQx3" }}>
        Checkout funnel
      </EvidenceRefChip>,
    );
    const link = screen.getByRole("link", { name: "Checkout funnel" });
    fireEvent.click(link);
    expect(openExternalUrl).toHaveBeenCalledWith(
      "https://us.posthog.com/project/2/insights/9pQx3",
    );
  });

  it("stays plain for a kind with no canonical page even when signed in", () => {
    signIn();
    renderInTheme(
      <EvidenceRefChip target={{ kind: "event", id: "cart_saved" }}>
        cart_saved events
      </EvidenceRefChip>,
    );
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("renders from an evidence: markdown link in agent output", () => {
    // Guards the whole path: url transform must keep the scheme and the `a`
    // component must dispatch to the chip instead of an external link.
    renderInTheme(
      <MarkdownRenderer content="The [coupon funnel](evidence:insight/9pQx3) dropped." />,
    );
    expect(screen.getByText("coupon funnel")).toBeDefined();
    // Without auth context the reference is not a link at all — a plain
    // external-link fallback would render one.
    expect(screen.queryByRole("link")).toBeNull();
  });
});

describe("EvidenceHoverCard", () => {
  it.each([
    ["loading", undefined, "evidence-preview-loading", "evidence-preview"],
    [
      "resolved",
      { title: "Checkout funnel", detail: "conversion, last 30 days" },
      "evidence-preview",
      "evidence-preview-loading",
    ],
    ["unavailable", null, null, "evidence-preview"],
  ])("shows the %s state", (_state, preview, shown, hidden) => {
    renderInTheme(
      <EvidenceHoverCard
        target={{ kind: "insight", id: "9pQx3" }}
        clickable={false}
        preview={preview}
      >
        Checkout funnel
      </EvidenceHoverCard>,
    );
    if (shown) expect(screen.getByTestId(shown)).toBeDefined();
    expect(screen.queryByTestId(hidden)).toBeNull();
    if (preview) {
      expect(screen.getByText("conversion, last 30 days")).toBeDefined();
    }
  });
});
