import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// quill-charts is canvas-backed and does not load in the test environment;
// the card chrome around it is what this test exercises.
vi.mock("@posthog/quill-charts", () => ({
  BarChart: () => <div data-testid="chart-plot" />,
  LineChart: () => <div data-testid="chart-plot" />,
  TimeSeriesBarChart: () => <div data-testid="chart-plot" />,
  TimeSeriesLineChart: () => <div data-testid="chart-plot" />,
  useChartTheme: () => ({}),
}));

import { MarkdownRenderer } from "./MarkdownRenderer";

const DATA_BLOCK = JSON.stringify({
  title: "Daily active users",
  render: "bar",
  labels: ["Aug 7", "Aug 8"],
  series: [{ name: "DAU", points: [69650, 39431] }],
});

describe("posthog-chart blocks in agent markdown", () => {
  it("renders a chart card instead of a code block", () => {
    // Guards the whole dispatch: the code component must parse the fence into
    // a card and the pre component must not wrap it in a code-block shell.
    render(
      <Theme>
        <MarkdownRenderer
          content={`Numbers:\n\n\`\`\`posthog-chart\n${DATA_BLOCK}\n\`\`\`\n`}
        />
      </Theme>,
    );
    expect(screen.getByTestId("report-chart")).toBeDefined();
    expect(screen.getByText("Daily active users")).toBeDefined();
    expect(screen.queryByText(/"series"/)).toBeNull();
  });

  it("renders nothing for a malformed or half-streamed block", () => {
    render(
      <Theme>
        <MarkdownRenderer
          content={'```posthog-chart\n{"series":[{"po\n```\n'}
        />
      </Theme>,
    );
    expect(screen.queryByTestId("report-chart")).toBeNull();
    expect(screen.queryByText(/series/)).toBeNull();
  });
});
