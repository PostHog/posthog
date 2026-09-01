import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { renderToStaticMarkup as renderMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

const queryClient = new QueryClient();
function renderStatic(node: ReactNode) {
  return renderMarkup(
    <QueryClientProvider client={queryClient}>{node}</QueryClientProvider>,
  );
}

// Chart cards resolve their data through the app shell's query client; here
// they stay in their loading state, which is all the dispatch tests need.
vi.mock("../../../../hooks/useAuthenticatedQuery", () => ({
  useAuthenticatedQuery: () => ({
    isPending: true,
    isError: false,
    isFetched: false,
    data: undefined,
  }),
}));
vi.mock("../../../auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => null,
}));

vi.mock("@posthog/ui/features/git-interaction/usePrDetails", () => ({
  usePrDetails: () => ({
    meta: {
      state: "open",
      merged: false,
      draft: false,
      headRefName: "posthog/status-chip",
      title: "Show pull request status in sessions",
      author: "octocat",
      isLoading: false,
    },
    commentThreads: new Map(),
    commentsLoading: false,
  }),
}));

vi.mock("@posthog/ui/features/pr-review/usePrChecks", () => ({
  usePrChecks: () => ({ data: [], isLoading: false }),
}));

import { ChatMarkdown, ChatStreamingMarkdown } from "./ChatMarkdown";

describe("ChatMarkdown", () => {
  it("preserves ordered-list numbering across intervening prose", () => {
    const content = `1. First review comment

Verdict: invalid.

2. Second review comment

Verdict: valid.

3. Third review comment`;

    const html = renderStatic(<ChatMarkdown content={content} />);

    expect(html).toContain('<ol start="2"');
    expect(html).toContain('<ol start="3"');
  });

  it("does not load remote markdown images", () => {
    const html = renderStatic(
      <ChatMarkdown content="![internal service](http://127.0.0.1/action)" />,
    );

    expect(html).toContain("Remote image blocked: internal service");
    expect(html).not.toContain("<img");
    expect(html).not.toContain("http://127.0.0.1/action");
  });

  it("renders a GitHub pull request with its live status chip", () => {
    const html = renderStatic(
      <ChatMarkdown content="Review https://github.com/PostHog/posthog/pull/23985" />,
    );

    expect(html).toContain("PostHog/posthog#23985");
    expect(html).toContain('aria-label="Open"');
    expect(html).toContain(
      'data-github-ref-url="https://github.com/PostHog/posthog/pull/23985"',
    );
  });

  it("labels a pull request review comment without dropping its anchor", () => {
    const href =
      "https://github.com/PostHog/posthog/pull/86811/changes#r3832262653";
    const html = renderStatic(<ChatMarkdown content={href} />);

    expect(html).toContain("Comment on PR #86811");
    expect(html).toContain(`data-github-ref-url="${href}"`);
  });
});

describe("ChatMarkdown object tags", () => {
  // The chat thread has its own sanitized renderer, which silently dropped
  // object tags while the session view rendered them; these lock the thread
  // to the same tag support.
  it("renders an inline object tag as a reference chip", () => {
    const html = renderStatic(
      <ChatMarkdown
        content={'The <insight id="9pQx3">checkout funnel</insight> dropped.'}
        renderObjectTags
      />,
    );
    expect(html).toContain("checkout funnel");
    expect(html).not.toContain("&lt;insight");
    // The chip's kind icon renders beside the label; a plain drop would not.
    expect(html).toContain("<svg");
  });

  it("renders a block hogql tag as a chart card, not code or raw text", () => {
    const html = renderStatic(
      <ChatMarkdown
        content={
          '<hogql display="block" title="DAU, last 7 days">SELECT 1</hogql>'
        }
        renderObjectTags
      />,
    );
    expect(html).toContain("report-chart");
    expect(html).toContain("DAU, last 7 days");
    expect(html).not.toContain("SELECT 1");
  });

  it("does not run object tags in untrusted content by default", () => {
    // User bubbles and other non-agent surfaces render without the opt-in;
    // their tags must never resolve to live queries or chart cards.
    const html = renderStatic(
      <ChatMarkdown
        content={
          '<hogql display="block" title="DAU">SELECT 1</hogql>\n\n```posthog-chart\n{"mode":"hogql","query":"SELECT 1"}\n```'
        }
      />,
    );
    expect(html).not.toContain("report-chart");
  });
});

describe("ChatStreamingMarkdown", () => {
  it("shows a pending link without exposing its incomplete destination", () => {
    const html = renderStatic(
      <ChatStreamingMarkdown content="Download [the report](https://example.com/report?token=secret" />,
    );

    expect(html).toContain("Download ");
    expect(html).toContain("the report");
    expect(html).not.toContain("example.com");
    expect(html).not.toContain("token=secret");
    expect(html).not.toContain("<a");
    expect(html).toContain('aria-label="Link loading"');
    expect(html).toContain("text-primary");
    expect(html).toContain("underline");
    expect(html).toContain("animate-spin");
  });

  it("renders the link when its destination is complete", () => {
    const html = renderStatic(
      <ChatStreamingMarkdown content="Download [the report](https://example.com/report)" />,
    );

    expect(html).toContain('href="https://example.com/report"');
    expect(html).toContain("the report");
  });
});
