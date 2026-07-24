import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ChatMarkdown } from "./ChatMarkdown";

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
