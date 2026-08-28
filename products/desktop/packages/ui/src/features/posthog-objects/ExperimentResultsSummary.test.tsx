import type { ExperimentResultsPresentation } from "@posthog/api-client/evidence-previews";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ExperimentResultsSummary } from "./ExperimentResultsSummary";

const variant = (
  key: string,
  overrides: Partial<
    ExperimentResultsPresentation["primaryMetrics"][number]["variants"][number]
  > = {},
) => ({
  key,
  isControl: key === "control",
  outcome: "125 · 12.5%",
  sampleContext: "1K samples · 1K exposed",
  uplift: key === "control" ? null : "+25.0%",
  upliftDirection: key === "control" ? null : ("positive" as const),
  isImprovement: key === "control" ? null : true,
  interval: key === "control" ? null : "+5.00% to +45.0%",
  pValue: key === "control" ? null : "0.020",
  chanceToWin: null,
  significance: key === "control" ? null : ("significant" as const),
  ...overrides,
});

const metric = (
  id: string,
  name: string,
  metricType: "primary" | "secondary",
  overrides: Partial<
    ExperimentResultsPresentation["primaryMetrics"][number]
  > = {},
) => ({
  id,
  name,
  metricType,
  state: "ready" as const,
  error: null,
  outcomeLabel: "Conversions",
  controlOutcome: "100 · 10.0% · 1K samples",
  bestVariant: {
    key: "test",
    uplift: "+25.0%",
    significance: "significant" as const,
    isImprovement: true,
  },
  variants: [variant("control"), variant("test")],
  ...overrides,
});

const results: ExperimentResultsPresentation = {
  state: "ready",
  stale: false,
  lastRefresh: "2026-01-15T12:00:00Z",
  primaryMetrics: [metric("primary-1", "Checkout conversion", "primary")],
  secondaryMetrics: [
    metric("secondary-1", "Orders per user", "secondary", {
      variants: [
        variant("control"),
        variant("test", { pValue: "0.120", significance: "not_significant" }),
      ],
      bestVariant: {
        key: "test",
        uplift: "+25.0%",
        significance: "not_significant",
        isImprovement: true,
      },
    }),
  ],
};

describe("ExperimentResultsSummary", () => {
  it("summarizes hover metrics and reveals a selected metric on demand", () => {
    render(
      <ExperimentResultsSummary
        display="compact"
        loadState="ready"
        results={results}
      />,
    );

    expect(screen.getAllByText("Best observed: test +25.0%")).toHaveLength(2);
    expect(screen.queryByText("p-value 0.020")).not.toBeInTheDocument();
    expect(screen.queryByText("p-value 0.120")).not.toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: /Checkout conversion/ }),
    );
    fireEvent.click(screen.getByRole("button", { name: /Orders per user/ }));

    expect(screen.getByText("p-value 0.020")).toBeInTheDocument();
    expect(screen.getByText("p-value 0.120")).toBeInTheDocument();
  });

  it("opens primary metrics on the full page and keeps secondary metrics collapsed", () => {
    render(
      <ExperimentResultsSummary
        display="full"
        loadState="ready"
        results={results}
      />,
    );

    expect(screen.getByText("p-value 0.020")).toBeInTheDocument();
    expect(
      screen.getByText("Control (control): 100 · 10.0% · 1K samples"),
    ).toBeInTheDocument();
    expect(screen.queryByText("p-value 0.120")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Orders per user/ }));

    expect(screen.getByText("p-value 0.120")).toBeInTheDocument();
  });

  it("caps hover cards at four metrics with a pointer to the full page", () => {
    const manyMetrics = {
      ...results,
      primaryMetrics: [
        metric("primary-1", "Metric one", "primary"),
        metric("primary-2", "Metric two", "primary"),
        metric("primary-3", "Metric three", "primary"),
      ],
      secondaryMetrics: [
        metric("secondary-1", "Metric four", "secondary"),
        metric("secondary-2", "Metric five", "secondary"),
        metric("secondary-3", "Metric six", "secondary"),
      ],
    };
    render(
      <ExperimentResultsSummary
        display="compact"
        loadState="ready"
        results={manyMetrics}
      />,
    );

    expect(screen.getByText("Metric four")).toBeInTheDocument();
    expect(screen.queryByText("Metric five")).not.toBeInTheDocument();
    expect(
      screen.getByText("+2 more metrics on the full page"),
    ).toBeInTheDocument();
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
