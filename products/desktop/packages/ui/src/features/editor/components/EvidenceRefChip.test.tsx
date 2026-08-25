import { POSTHOG_OBJECT_KINDS } from "@posthog/core/message-editor/content";
import { useDraftStore } from "@posthog/ui/features/message-editor/draftStore";
import { SessionTaskIdProvider } from "@posthog/ui/features/sessions/useSessionTaskId";
import { Theme } from "@radix-ui/themes";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../../../shell/openExternal", () => ({
  openExternalUrl: vi.fn(),
}));

// The hover card resolves its preview through the app shell; without it the
// loader renders the static card, which is all the chip tests need.
vi.mock("../../auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => null,
}));
vi.mock("../../../hooks/useAuthenticatedQuery", () => ({
  useAuthenticatedQuery: () => ({
    isPending: true,
    isError: false,
    isFetched: false,
    data: undefined,
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
  const actions = useDraftStore.getState().actions;
  actions.setDraft("task-1", null);
  actions.clearPendingInsert("task-1");
  actions.clearFocusRequest("task-1");
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
      <MarkdownRenderer
        content="The [coupon funnel](evidence:insight/9pQx3) dropped."
        renderObjectTags
      />,
    );
    expect(screen.getByText("coupon funnel")).toBeDefined();
    // Without auth context the reference is not a link at all — a plain
    // external-link fallback would render one.
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("opens the card from keyboard focus on a linked reference", () => {
    signIn();
    renderInTheme(
      <EvidenceRefChip target={{ kind: "insight", id: "9pQx3" }}>
        Checkout funnel
      </EvidenceRefChip>,
    );
    const link = screen.getByRole("link", { name: "Checkout funnel" });
    fireEvent.focus(link);
    // The card is a focus-managed dialog, not a tooltip: its controls are
    // real elements a keyboard user can Tab to.
    const dialog = screen.getByRole("dialog");
    expect(dialog).toBeDefined();
    expect(
      screen.getByRole("button", { name: /Open in PostHog/ }),
    ).toBeDefined();
  });

  it("gives an unlinked reference a focusable trigger that opens the card", () => {
    // A flag cited by key or an event cited by name has no chip URL, so the
    // card's "Open in PostHog" is the only route to the object; the trigger
    // must therefore be reachable and operable by keyboard.
    signIn();
    renderInTheme(
      <EvidenceRefChip target={{ kind: "event", id: "cart_saved" }}>
        cart_saved events
      </EvidenceRefChip>,
    );
    const trigger = screen.getByRole("button", { name: "cart_saved events" });
    expect(trigger.getAttribute("tabindex")).toBe("0");
    fireEvent.click(trigger);
    expect(screen.getByRole("dialog")).toBeDefined();
  });

  it.each(POSTHOG_OBJECT_KINDS)(
    "offers the compact composer action for %s references",
    (kind) => {
      renderInTheme(
        <SessionTaskIdProvider taskId="task-1">
          <EvidenceRefChip target={{ kind, id: `${kind}-1` }}>
            {kind} reference
          </EvidenceRefChip>
        </SessionTaskIdProvider>,
      );

      fireEvent.focus(screen.getByRole("link", { name: `${kind} reference` }));
      expect(
        screen.getByRole("button", { name: "Ask about this" }),
      ).toBeDefined();
    },
  );

  it("hides the composer action outside a task conversation", () => {
    renderInTheme(
      <EvidenceRefChip target={{ kind: "flag", id: "new-checkout" }}>
        new-checkout
      </EvidenceRefChip>,
    );

    fireEvent.click(screen.getByRole("button", { name: "new-checkout" }));
    expect(screen.queryByRole("button", { name: "Ask about this" })).toBeNull();
  });

  it("adds the exact object reference after an existing composer draft", () => {
    signIn();
    useDraftStore.getState().actions.setDraft("task-1", {
      segments: [{ type: "text", text: "Compare the variants" }],
    });
    renderInTheme(
      <SessionTaskIdProvider taskId="task-1">
        <EvidenceRefChip target={{ kind: "insight", id: "9pQx3" }}>
          Checkout funnel
        </EvidenceRefChip>
      </SessionTaskIdProvider>,
    );

    fireEvent.focus(screen.getByRole("link", { name: "Checkout funnel" }));
    fireEvent.click(screen.getByRole("button", { name: "Ask about this" }));

    expect(useDraftStore.getState().pendingInsert["task-1"]).toEqual({
      segments: [
        { type: "text", text: "\n\nAsk about " },
        {
          type: "chip",
          chip: {
            type: "posthog_object",
            objectKind: "insight",
            id: "9pQx3",
            label: "Insight: Checkout funnel",
          },
        },
        { type: "text", text: " " },
      ],
    });
    expect(useDraftStore.getState().focusRequested["task-1"]).toBeDefined();
    expect(screen.queryByRole("dialog")).toBeNull();
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

  it("copies the exact reference from the existing footer", () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    renderInTheme(
      <EvidenceHoverCard
        target={{ kind: "insight", id: "9pQx3" }}
        url={null}
        preview={{ title: "Checkout funnel" }}
      >
        Checkout funnel
      </EvidenceHoverCard>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Copy reference" }));

    expect(writeText).toHaveBeenCalledWith("9pQx3");
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

  it("hangs bar-sparkline negatives below the shared zero baseline", () => {
    renderInTheme(
      <EvidenceHoverCard
        target={{ kind: "hogql", id: "SELECT 1" }}
        url={null}
        preview={{
          title: "change by category",
          spark: { points: [-10, 5], render: "bar" },
        }}
      >
        per-category change
      </EvidenceHoverCard>,
    );
    const bars = screen
      .getByTestId("evidence-sparkline")
      .querySelectorAll("rect");
    expect(bars).toHaveLength(2);
    const y = (el: Element) => Number(el.getAttribute("y"));
    const h = (el: Element) => Number(el.getAttribute("height"));
    // Zero line sits at y≈10.67: the -10 bar hangs below it with real height
    // (not the 0.5 clamp it collapsed to when measured from the chart bottom),
    // and the +5 bar rises from that same baseline.
    expect(y(bars[0])).toBeCloseTo(10.67, 1);
    expect(h(bars[0])).toBeCloseTo(17.33, 1);
    expect(y(bars[1]) + h(bars[1])).toBeCloseTo(10.67, 1);
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
