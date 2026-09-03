import type { EvidenceCardData } from "@posthog/ui/features/editor/evidencePreview";
import { Theme } from "@radix-ui/themes";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PostHogObjectPage } from "./PostHogObjectPage";

const writeText = vi.fn().mockResolvedValue(undefined);
// Mirror the real hook: a flag page resolves only from a numeric id, so the
// link is available only if the page passes the resolved id, not the key.
const useEvidenceUrl = vi.hoisted(() =>
  vi.fn((_kind: string, id: string) =>
    /^\d+$/.test(id)
      ? `https://us.posthog.com/project/2/feature_flags/${id}`
      : null,
  ),
);

// quill-charts is canvas-backed and does not load in the test environment;
// the card chrome around it is what these tests exercise.
vi.mock("@posthog/quill-charts", () => ({
  BarChart: () => <div data-testid="chart-plot" />,
  LineChart: () => <div data-testid="chart-plot" />,
  TimeSeriesBarChart: () => <div data-testid="chart-plot" />,
  TimeSeriesLineChart: () => <div data-testid="chart-plot" />,
  useChartTheme: () => ({}),
}));

// The page reads the shared evidence-preview entry. Each test sets the cache
// state it needs through this mutable stand-in.
const queryState = vi.hoisted(() => ({
  current: {
    isPending: false,
    isError: false,
    data: {
      title: "new-checkout-flow",
      detail: "Enabled",
      // The preview resolves the flag key to its numeric id.
      resolvedId: "42",
      facts: ["100% rollout", "Used by 1 experiment"],
      sections: [
        {
          title: "Configuration",
          fields: [
            { label: "Type", value: "Boolean" },
            { label: "Release conditions", value: "All users" },
          ],
        },
      ],
    } as EvidenceCardData | null,
  },
}));

vi.mock("@posthog/ui/hooks/useAuthenticatedQuery", () => ({
  useAuthenticatedQuery: () => ({
    isPending: queryState.current.isPending,
    isError: queryState.current.isError,
    data: queryState.current.data,
  }),
}));

vi.mock("@posthog/ui/features/editor/components/EvidenceRefChip", () => ({
  useEvidenceUrl,
  EvidenceSparkline: () => null,
}));

function setQueryState(state: {
  isPending?: boolean;
  isError?: boolean;
  data?: EvidenceCardData | null;
}): void {
  queryState.current = {
    isPending: state.isPending ?? false,
    isError: state.isError ?? false,
    data: state.data ?? null,
  };
}

describe("PostHogObjectPage", () => {
  it("renders live reference details and copies the exact identifier", async () => {
    setQueryState({
      data: {
        title: "new-checkout-flow",
        detail: "Enabled",
        resolvedId: "42",
        facts: ["100% rollout", "Used by 1 experiment"],
        sections: [
          {
            title: "Configuration",
            fields: [
              { label: "Type", value: "Boolean" },
              { label: "Release conditions", value: "All users" },
            ],
          },
        ],
      },
    });
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    render(
      <Theme>
        <PostHogObjectPage
          fallbackName="Flag fallback"
          metadata={{
            reference_type: "posthog_object",
            object_kind: "flag",
            object_id: "new-checkout-flow",
            source_message_ids: ["turn-1", "turn-2"],
            occurrence_count: 2,
          }}
        />
      </Theme>,
    );

    expect(screen.getAllByText("new-checkout-flow")).toHaveLength(2);
    expect(screen.getByText("100% rollout")).toBeInTheDocument();
    expect(useEvidenceUrl).toHaveBeenLastCalledWith("flag", "42");
    expect(screen.getByText("Configuration")).toBeInTheDocument();
    expect(screen.getByText("Release conditions")).toBeInTheDocument();
    expect(screen.getByText("All users")).toBeInTheDocument();
    expect(
      screen.getByText("Referenced 2 times in this task"),
    ).toBeInTheDocument();
    // A flag cited by key still links out, via the resolved numeric id.
    expect(screen.getByText(/Open in PostHog/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Copy ID" }));
    expect(writeText).toHaveBeenCalledWith("new-checkout-flow");
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "ID copied" }),
      ).toBeInTheDocument(),
    );
  });

  it("draws an insight's chart from the cached preview, with no loading state", () => {
    setQueryState({
      data: {
        title: "Checkout funnel",
        chartData: { type: "number", value: 68831577 },
      },
    });
    render(
      <Theme>
        <PostHogObjectPage
          fallbackName="Checkout funnel"
          metadata={{
            reference_type: "posthog_object",
            object_kind: "insight",
            object_id: "9pQx3",
            source_message_ids: ["turn-1"],
            occurrence_count: 1,
          }}
        />
      </Theme>,
    );

    // The chart renders from the warmed cache: value present, no skeleton.
    expect(screen.getByTestId("report-chart")).toBeInTheDocument();
    expect(screen.getByText("68,831,577")).toBeInTheDocument();
  });

  it("shows a chart skeleton while the insight preview loads", () => {
    setQueryState({ isPending: true, data: null });
    render(
      <Theme>
        <PostHogObjectPage
          fallbackName="Checkout funnel"
          metadata={{
            reference_type: "posthog_object",
            object_kind: "insight",
            object_id: "9pQx3",
            source_message_ids: ["turn-1"],
            occurrence_count: 1,
          }}
        />
      </Theme>,
    );

    expect(screen.queryByTestId("report-chart")).toBeNull();
  });

  it("reports an insight the project does not resolve", () => {
    setQueryState({ data: null });
    render(
      <Theme>
        <PostHogObjectPage
          fallbackName="Missing insight"
          metadata={{
            reference_type: "posthog_object",
            object_kind: "insight",
            object_id: "nope",
            source_message_ids: ["turn-1"],
            occurrence_count: 1,
          }}
        />
      </Theme>,
    );

    expect(
      screen.getByText(/No insight matches "nope" in the current project/),
    ).toBeInTheDocument();
  });

  it("never titles a hogql chart card with raw SQL", () => {
    setQueryState({
      data: {
        title: "Events by day",
        chartData: {
          type: "series",
          labels: ["2026-08-13", "2026-08-14"],
          series: [
            {
              key: "series-0",
              label: "arrayJoin(events.event)",
              data: [5096547, 1506301],
            },
          ],
          render: "line",
          isTimeSeries: true,
          interval: "day",
        },
      },
    });
    render(
      <Theme>
        <PostHogObjectPage
          fallbackName="Events by day"
          metadata={{
            reference_type: "posthog_object",
            object_kind: "hogql",
            object_id: "SELECT arrayJoin(events.event) ...",
            source_message_ids: ["turn-1"],
            occurrence_count: 1,
          }}
        />
      </Theme>,
    );

    expect(screen.getByTestId("report-chart")).toBeInTheDocument();
    // The card title is the page title (header + card both show it); the raw
    // SQL series label only ever reaches the (mocked) chart plot, not the DOM.
    expect(screen.getAllByText("Events by day").length).toBeGreaterThan(0);
    expect(screen.queryByText("arrayJoin(events.event)")).toBeNull();
  });
});
