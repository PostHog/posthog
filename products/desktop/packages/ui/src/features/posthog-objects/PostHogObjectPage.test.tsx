import type { EvidenceCardData } from "@posthog/ui/features/editor/evidencePreview";
import { Theme } from "@radix-ui/themes";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PostHogObjectPage } from "./PostHogObjectPage";

const writeText = vi.fn().mockResolvedValue(undefined);
const useEvidenceUrl = vi.hoisted(() =>
  vi.fn((_kind: string, id: string) =>
    /^\d+$/.test(id)
      ? `https://us.posthog.com/project/2/feature_flags/${id}`
      : null,
  ),
);

vi.mock("@posthog/quill-charts", () => ({
  BarChart: () => <div data-testid="chart-plot" />,
  LineChart: () => <div data-testid="chart-plot" />,
  TimeSeriesBarChart: () => <div data-testid="chart-plot" />,
  TimeSeriesLineChart: () => <div data-testid="chart-plot" />,
  useChartTheme: () => ({}),
}));

const queryState = vi.hoisted(() => ({
  current: {
    isPending: false,
    isError: false,
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
        // hogqlPreview puts the first result column in the hover title.
        title: "arrayJoin(events.event)",
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
    // The page header and chart card use the chip label, never the raw SQL
    // the hover reduction stored in the preview title or series label.
    expect(screen.getAllByText("Events by day").length).toBeGreaterThan(0);
    expect(screen.queryByText("arrayJoin(events.event)")).toBeNull();
  });

  it("keeps a multi-series insight's series labels out of the page subtitle", () => {
    setQueryState({
      data: {
        title: "Checkout funnel",
        // insightPreview stores joined series labels in the hover detail.
        detail: "control · aggressive",
        description: "Daily unique visitors",
        chartData: {
          type: "series",
          labels: ["2026-08-13", "2026-08-14"],
          series: [
            { key: "series-0", label: "control", data: [40, 44] },
            { key: "series-1", label: "aggressive", data: [38, 45] },
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

    // The subtitle shows the insight's description, not the series labels.
    expect(screen.getByText(/Daily unique visitors/)).toBeInTheDocument();
    expect(screen.queryByText(/control · aggressive/)).toBeNull();
  });

  it("keeps a multi-series hogql query's column labels out of the page subtitle", () => {
    setQueryState({
      data: {
        title: "ifNull(count(), 0)",
        // hogqlPreview joins the result columns into the hover detail.
        detail: "ifNull(count(), 0) · arrayJoin(events.event)",
        chartData: {
          type: "series",
          labels: ["2026-08-13", "2026-08-14"],
          series: [
            { key: "series-0", label: "ifNull(count(), 0)", data: [40, 44] },
            {
              key: "series-1",
              label: "arrayJoin(events.event)",
              data: [38, 45],
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
            object_id: "SELECT arrayJoin(events.event), ifNull(count(), 0) ...",
            source_message_ids: ["turn-1"],
            occurrence_count: 1,
          }}
        />
      </Theme>,
    );

    // The subtitle shows kind and source only, never the raw SQL detail.
    expect(screen.queryByText(/ifNull\(count\(\), 0\)/)).toBeNull();
    expect(screen.queryByText(/arrayJoin\(events\.event\)/)).toBeNull();
  });
});
