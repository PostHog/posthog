import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ChatMarkdown, ChatStreamingMarkdown } from "./ChatMarkdown";

describe("ChatMarkdown", () => {
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
  it("shows the label without exposing an incomplete link destination", () => {
    const html = renderToStaticMarkup(
      <ChatStreamingMarkdown content="Download [the report](https://example.com/report?token=secret" />,
    );

    expect(html).toContain("Download the report");
    expect(html).not.toContain("example.com");
    expect(html).not.toContain("token=secret");
    expect(html).not.toContain("<a");
  });

  it("renders the link when its destination is complete", () => {
    const html = renderToStaticMarkup(
      <ChatStreamingMarkdown content="Download [the report](https://example.com/report)" />,
    );

    expect(html).toContain('href="https://example.com/report"');
    expect(html).toContain("the report");
  });
});
