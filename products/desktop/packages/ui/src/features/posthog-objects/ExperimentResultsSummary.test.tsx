import type { ExperimentResultsPresentation } from "@posthog/api-client/evidence-previews";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ExperimentResultsSummary } from "./ExperimentResultsSummary";

const results: ExperimentResultsPresentation = {
  state: "ready",
  stale: false,
  lastRefresh: "2026-01-15T12:00:00Z",
  primaryMetrics: [
    {
      id: "primary-1",
      name: "Checkout conversion",
      metricType: "primary",
      state: "ready",
      error: null,
      outcomeLabel: "Conversions",
      variants: [
        {
          key: "control",
          isControl: true,
          outcome: "100 · 10.0%",
          sampleContext: "1K samples · 1.1K exposed",
          uplift: null,
          interval: null,
          pValue: null,
          chanceToWin: null,
          significance: null,
        },
        {
          key: "test",
          isControl: false,
          outcome: "125 · 12.5%",
          sampleContext: "1K samples · 1K exposed",
          uplift: "+25.0%",
          interval: "+5.00% to +45.0%",
          pValue: "0.020",
          chanceToWin: null,
          significance: "significant",
        },
      ],
    },
  ],
  secondaryMetrics: [
    {
      id: "secondary-1",
      name: "Orders per user",
      metricType: "secondary",
      state: "ready",
      error: null,
      outcomeLabel: "Outcome",
      variants: [],
    },
  ],
};

describe("ExperimentResultsSummary", () => {
  it("keeps hover results concise until the user asks for all statistics", () => {
    render(
      <ExperimentResultsSummary
        display="compact"
        loadState="ready"
        results={results}
      />,
    );

    expect(screen.getByText("Checkout conversion")).toBeInTheDocument();
    expect(screen.queryByText("Orders per user")).not.toBeInTheDocument();
    expect(screen.queryByText("p-value 0.020")).not.toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", {
        name: "Show all 2 metrics and statistics",
      }),
    );

    expect(screen.getByText("Orders per user")).toBeInTheDocument();
    expect(screen.getByText("p-value 0.020")).toBeInTheDocument();
    expect(
      screen.getByText("95% interval +5.00% to +45.0%"),
    ).toBeInTheDocument();
    expect(screen.getByText("Significant")).toBeInTheDocument();
  });

  it("shows the complete variant result on the full page", () => {
    render(
      <ExperimentResultsSummary
        display="full"
        loadState="ready"
        results={results}
      />,
    );

    expect(screen.getByText("Checkout conversion")).toBeInTheDocument();
    expect(screen.getByText("Orders per user")).toBeInTheDocument();
    expect(screen.getByText("+25.0%")).toBeInTheDocument();
    expect(screen.getByText("+5.00% to +45.0%")).toBeInTheDocument();
    expect(screen.getByText("p-value 0.020")).toBeInTheDocument();
  });

  it.each([
    ["loading", "loading", null, "experiment-results-loading"],
    [
      "failed lookup",
      "error",
      null,
      "Couldn't load experiment results. Try again, or open the experiment in PostHog.",
    ],
    [
      "draft",
      "ready",
      { ...results, state: "draft" },
      "Results will appear after this experiment starts.",
    ],
    [
      "insufficient data",
      "ready",
      { ...results, state: "insufficient_data" },
      "There isn't enough data to determine significance yet.",
    ],
  ] as const)(
    "renders the %s state",
    (_name, loadState, stateResults, expected) => {
      render(
        <ExperimentResultsSummary
          display="compact"
          loadState={loadState}
          results={stateResults}
        />,
      );

      if (expected === "experiment-results-loading") {
        expect(screen.getByTestId(expected)).toBeInTheDocument();
      } else {
        expect(screen.getByText(expected)).toBeInTheDocument();
      }
    },
  );
});
