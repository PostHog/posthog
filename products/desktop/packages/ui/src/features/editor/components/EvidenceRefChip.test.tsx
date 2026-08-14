import { Theme } from "@radix-ui/themes";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../../../shell/openExternal", () => ({
  openExternalUrl: vi.fn(),
}));

// The replay hover card mounts the shared player area, which resolves the
// sharing state through the app shell; "not shared yet" is enough here.
vi.mock("../../auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => null,
}));
vi.mock("../../../hooks/useAuthenticatedQuery", () => ({
  useAuthenticatedQuery: () => ({
    isPending: false,
    isError: false,
    data: { enabled: false, embedUrl: null },
  }),
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
        url={null}
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

  it("draws a sparkline and headline for a series preview and opens on click", () => {
    const onOpen = vi.fn();
    renderInTheme(
      <EvidenceHoverCard
        target={{ kind: "hogql", id: "SELECT 1" }}
        url="https://us.posthog.com/project/2/sql?open_query=SELECT%201"
        onOpen={onOpen}
        preview={{
          title: "active_users",
          headline: {
            value: "1.5M",
            delta: { label: "71%", direction: "down" },
          },
          spark: { points: [5, 5.1, 5.7, 1.5], render: "line" },
        }}
      >
        active users per day
      </EvidenceHoverCard>,
    );
    expect(screen.getByTestId("evidence-sparkline")).toBeDefined();
    expect(screen.getByText("1.5M")).toBeDefined();
    fireEvent.click(screen.getByRole("button", { name: /Open in PostHog/ }));
    expect(onOpen).toHaveBeenCalledWith(
      "https://us.posthog.com/project/2/sql?open_query=SELECT%201",
    );
  });

  it("expands the truncated SQL footer into the full query on click", () => {
    const sql =
      "SELECT toDate(timestamp) AS day, count() FROM events GROUP BY day";
    renderInTheme(
      <EvidenceHoverCard
        target={{ kind: "hogql", id: sql }}
        url={null}
        preview={{ title: "day" }}
      >
        events per day
      </EvidenceHoverCard>,
    );
    expect(screen.queryByTestId("evidence-query")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /SELECT toDate/ }));
    expect(screen.getByTestId("evidence-query").textContent).toBe(sql);
    fireEvent.click(screen.getByRole("button", { name: "Hide query" }));
    expect(screen.queryByTestId("evidence-query")).toBeNull();
  });

  it("offers the in-card player for a replay reference", () => {
    renderInTheme(
      <EvidenceHoverCard
        target={{ kind: "replay", id: "s_01HQ4K" }}
        url={null}
        preview={{ title: "Session by ann@example.com" }}
      >
        14 recordings
      </EvidenceHoverCard>,
    );
    expect(screen.getByRole("button", { name: /Watch here/ })).toBeDefined();
  });

  it("renders preview facts as pills", () => {
    renderInTheme(
      <EvidenceHoverCard
        target={{ kind: "flag", id: "42" }}
        url={null}
        preview={{
          title: "new-checkout-flow",
          detail: "Enabled",
          facts: ["100% rollout", "Used by 1 experiment"],
        }}
      >
        new-checkout-flow
      </EvidenceHoverCard>,
    );
    expect(screen.getByText("100% rollout")).toBeDefined();
    expect(screen.getByText("Used by 1 experiment")).toBeDefined();
  });
});
