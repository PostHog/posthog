import { Theme } from "@radix-ui/themes";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// quill-charts is canvas-backed and does not load in the test environment;
// the tag-to-card dispatch around it is what these tests exercise.
vi.mock("@posthog/quill-charts", () => ({
  BarChart: () => <div data-testid="chart-plot" />,
  LineChart: () => <div data-testid="chart-plot" />,
  TimeSeriesBarChart: () => <div data-testid="chart-plot" />,
  TimeSeriesLineChart: () => <div data-testid="chart-plot" />,
  useChartTheme: () => ({}),
}));

// Cards resolve their data through the app shell; without it they render
// their loading state, which is all the dispatch tests need.
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

import { MarkdownRenderer } from "./MarkdownRenderer";

const queryClient = new QueryClient();

function renderMarkdown(content: string) {
  return render(
    <QueryClientProvider client={queryClient}>
      <Theme>
        <MarkdownRenderer content={content} renderObjectTags />
      </Theme>
    </QueryClientProvider>,
  );
}

function renderUntrustedMarkdown(content: string) {
  return render(
    <QueryClientProvider client={queryClient}>
      <Theme>
        <MarkdownRenderer content={content} />
      </Theme>
    </QueryClientProvider>,
  );
}

describe("object tags in agent markdown", () => {
  it("renders an inline object tag as a reference chip with its label", () => {
    renderMarkdown(
      'The <insight id="9pQx3">checkout funnel</insight> dropped.',
    );
    expect(screen.getByText("checkout funnel")).toBeDefined();
    expect(screen.queryByText(/<insight/)).toBeNull();
  });

  it("falls back to the id as the label for a self-closing tag", () => {
    renderMarkdown('Gated by <flag id="42"/> since Jan 3.');
    expect(screen.getByText("42")).toBeDefined();
    expect(screen.queryByText(/<flag/)).toBeNull();
  });

  it("keeps markdown formatting inside a tag label", () => {
    renderMarkdown(
      'See <error id="018f">the **CouponValidator** issue</error>.',
    );
    expect(screen.getByText("CouponValidator").tagName).toBe("STRONG");
  });

  it.each([
    ["session-replay", '<session-replay id="s1">a recording</session-replay>'],
    ["feature-flag", '<feature-flag id="7">the flag</feature-flag>'],
  ])("resolves the %s alias", (_alias, tag) => {
    renderMarkdown(`Watch ${tag} now.`);
    expect(screen.queryByText(/</)).toBeNull();
  });

  it("shows an inline hogql tag as its label, not its SQL", () => {
    renderMarkdown(
      'We saw <hogql label="signups today">SELECT count() FROM events</hogql> spike.',
    );
    expect(screen.getByText("signups today")).toBeDefined();
    expect(screen.queryByText(/SELECT count/)).toBeNull();
  });

  it("renders a block insight tag as a chart card", () => {
    renderMarkdown('Here it is:\n\n<insight id="9pQx3" display="block"/>\n');
    expect(screen.getByTestId("report-chart")).toBeDefined();
  });

  it("renders a block hogql tag as a chart card titled from the tag", () => {
    renderMarkdown(
      '<hogql display="block" title="DAU, last 7 days">\nSELECT 1\n</hogql>\n',
    );
    expect(screen.getByTestId("report-chart")).toBeDefined();
    expect(screen.getByText("DAU, last 7 days")).toBeDefined();
    expect(screen.queryByText(/SELECT 1/)).toBeNull();
  });

  it("renders a block replay tag as a watchable card", () => {
    renderMarkdown('Watch it:\n\n<replay id="s_01HQ4K" display="block"/>\n');
    expect(screen.getByTestId("replay-card")).toBeDefined();
  });

  it("lifts a single-line block tag out of its paragraph into a card", () => {
    // Markdown parses `<hogql ...>SELECT ...</hogql>` on one line as inline
    // html inside a paragraph, not an HTML block; without the lift it would
    // downgrade to an inline chip.
    renderMarkdown(
      '<hogql display="block" title="One-liner">SELECT 1</hogql>\n',
    );
    expect(screen.getByTestId("report-chart")).toBeDefined();
    expect(screen.getByText("One-liner")).toBeDefined();
  });

  it.each([
    [
      "a list item",
      '- Signups jumped:\n\n  <hogql display="block" title="Nested chart">SELECT 1</hogql>\n',
    ],
    [
      "a blockquote",
      '> Note:\n>\n> <hogql display="block" title="Nested chart">SELECT 1</hogql>\n',
    ],
  ])("renders a block tag nested in %s as a chart card", (_where, content) => {
    renderMarkdown(content);
    expect(screen.getByTestId("report-chart")).toBeDefined();
    expect(screen.getByText("Nested chart")).toBeDefined();
    expect(screen.queryByText(/SELECT 1/)).toBeNull();
  });

  it("leaves tags inside code fences literal", () => {
    const { container } = renderMarkdown(
      'Example:\n\n```xml\n<insight id="9pQx3">label</insight>\n```\n',
    );
    expect(container.querySelector("code")?.textContent).toContain(
      '<insight id="9pQx3">',
    );
    expect(screen.queryByTestId("report-chart")).toBeNull();
  });

  it("renders nothing for a half-streamed tag instead of raw text", () => {
    renderMarkdown('<hogql display="block" title="DAU">\nSELECT 1');
    expect(screen.queryByText(/hogql|SELECT/)).toBeNull();
  });

  it("leaves unknown tags unrendered rather than guessing", () => {
    renderMarkdown('A <made-up-tag id="1">thing</made-up-tag> here.');
    expect(screen.queryByTestId("report-chart")).toBeNull();
    // The label text still flows through; only the tags themselves vanish.
    expect(screen.getByText(/thing/)).toBeDefined();
  });

  it("caps block cards per message; overflow degrades to inline chips", () => {
    // Every block card executes a query on mount, so one message must not
    // fan out unbounded concurrent queries. Past the cap (10) a block tag
    // renders as a hover-gated inline chip instead.
    const tags = Array.from(
      { length: 12 },
      (_, i) => `<hogql display="block" title="Q${i}">SELECT ${i}</hogql>\n`,
    ).join("\n");
    renderMarkdown(tags);
    expect(screen.getAllByTestId("report-chart")).toHaveLength(10);
    // The two overflow tags fall back to the inline chip's default label.
    expect(screen.getAllByText("SQL query")).toHaveLength(2);
  });
});

describe("object tags in untrusted markdown (default)", () => {
  it("does not render a block tag as a live chart card", () => {
    renderUntrustedMarkdown(
      'Here it is:\n\n<hogql display="block" title="DAU">\nSELECT 1\n</hogql>\n',
    );
    expect(screen.queryByTestId("report-chart")).toBeNull();
  });

  it("does not render a posthog-chart fence as a live chart card", () => {
    const { container } = renderUntrustedMarkdown(
      '```posthog-chart\n{"mode":"hogql","query":"SELECT 1"}\n```\n',
    );
    expect(screen.queryByTestId("report-chart")).toBeNull();
    expect(container.querySelector("code")?.textContent).toContain(
      '"mode":"hogql"',
    );
  });

  it("does not render an evidence: link as a reference chip", () => {
    const { container } = renderUntrustedMarkdown(
      "See [errors today](evidence:hogql/SELECT%201).",
    );
    // The href is stripped by the default url transform, so the chip (whose
    // hover preview would run the query) never mounts.
    expect(container.querySelector('a[href^="evidence:"]')).toBeNull();
    expect(screen.getByText("errors today")).toBeDefined();
  });
});
