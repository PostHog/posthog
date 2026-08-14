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

// Chart cards resolve their data through the app shell's query client; here
// they stay in their loading state, which still proves the dispatch.
vi.mock("../../../hooks/useAuthenticatedQuery", () => ({
  useAuthenticatedQuery: () => ({
    isPending: true,
    isError: false,
    isFetched: false,
    data: undefined,
  }),
}));

import { MarkdownRenderer } from "./MarkdownRenderer";

describe("posthog-chart blocks in agent markdown", () => {
  it("renders the internal chart node as a card instead of a code block", () => {
    // remarkObjectTags emits these code nodes for block-display tags; the
    // code component must parse them into a card and the pre component must
    // not wrap the card in a code-block shell.
    render(
      <Theme>
        <MarkdownRenderer
          content={
            '```posthog-chart\n{"mode":"hogql","query":"SELECT 1","title":"Daily active users"}\n```\n'
          }
        />
      </Theme>,
    );
    expect(screen.getByTestId("report-chart")).toBeDefined();
    expect(screen.getByText("Daily active users")).toBeDefined();
    expect(screen.queryByText(/"query"/)).toBeNull();
    expect(screen.queryByLabelText("Copy code")).toBeNull();
  });

  it("leaves ordinary fenced code inside the code-block shell", () => {
    // The chart dispatch widened the fence-language regex and made `pre`
    // conditionally unwrap; a plain fence must keep its highlighted
    // code-block chrome and never become a chart card.
    const { container } = render(
      <Theme>
        <MarkdownRenderer content={"```ts\nconst a = 1;\n```\n"} />
      </Theme>,
    );
    // Highlighting splits the code into spans, so match the joined text.
    expect(container.querySelector("code")?.textContent).toBe("const a = 1;");
    expect(screen.getByLabelText("Copy code")).toBeDefined();
    expect(screen.queryByTestId("report-chart")).toBeNull();
  });

  it("renders nothing for a malformed or half-streamed block", () => {
    render(
      <Theme>
        <MarkdownRenderer
          content={'```posthog-chart\n{"mode":"hogql","que\n```\n'}
        />
      </Theme>,
    );
    expect(screen.queryByTestId("report-chart")).toBeNull();
    expect(screen.queryByText(/mode/)).toBeNull();
  });
});
