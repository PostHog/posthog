import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ChatMarkdown, ChatStreamingMarkdown } from "./ChatMarkdown";

describe("ChatMarkdown", () => {
  it("preserves ordered-list numbering across intervening prose", () => {
    const content = `1. First review comment

Verdict: invalid.

2. Second review comment

Verdict: valid.

3. Third review comment`;

    const html = renderToStaticMarkup(<ChatMarkdown content={content} />);

    expect(html).toContain('<ol start="2"');
    expect(html).toContain('<ol start="3"');
  });

  it("does not load remote markdown images", () => {
    const html = renderToStaticMarkup(
      <ChatMarkdown content="![internal service](http://127.0.0.1/action)" />,
    );

    expect(html).toContain("Remote image blocked: internal service");
    expect(html).not.toContain("<img");
    expect(html).not.toContain("http://127.0.0.1/action");
  });
});

describe("ChatStreamingMarkdown", () => {
  it("shows a pending link without exposing its incomplete destination", () => {
    const html = renderToStaticMarkup(
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
    const html = renderToStaticMarkup(
      <ChatStreamingMarkdown content="Download [the report](https://example.com/report)" />,
    );

    expect(html).toContain('href="https://example.com/report"');
    expect(html).toContain("the report");
  });
});
