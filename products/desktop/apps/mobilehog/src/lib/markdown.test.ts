import { marked, type Token, type Tokens } from "marked";
import { describe, expect, it } from "vitest";
import { isLoadableImageUrl, splitImageRuns } from "./markdown";

function paragraphTokens(text: string): Token[] {
  const [paragraph] = marked.lexer(text) as Tokens.Paragraph[];
  return paragraph.tokens;
}

describe("splitImageRuns", () => {
  it("keeps a paragraph without images as one text run", () => {
    const runs = splitImageRuns(paragraphTokens("Just **text** here."));
    expect(runs).toHaveLength(1);
    expect(runs[0].kind).toBe("text");
  });

  it("lifts a lone image into an image run", () => {
    const runs = splitImageRuns(
      paragraphTokens("![A chart](https://example.com/chart.png)"),
    );
    expect(runs).toEqual([
      {
        kind: "image",
        token: expect.objectContaining({
          href: "https://example.com/chart.png",
          text: "A chart",
        }),
      },
    ]);
  });

  it("splits text around an inline image", () => {
    const runs = splitImageRuns(
      paragraphTokens("Before ![x](https://example.com/x.png) after"),
    );
    expect(runs.map((run) => run.kind)).toEqual(["text", "image", "text"]);
  });

  it("drops whitespace between images", () => {
    const runs = splitImageRuns(
      paragraphTokens(
        "![a](https://example.com/a.png) ![b](https://example.com/b.png)",
      ),
    );
    expect(runs.map((run) => run.kind)).toEqual(["image", "image"]);
  });

  it("keeps images with unsafe URLs inline", () => {
    const runs = splitImageRuns(
      paragraphTokens("See ![secret](file:///etc/passwd) now"),
    );
    expect(runs).toHaveLength(1);
    expect(runs[0].kind).toBe("text");
  });

  it("leaves images nested in links inline", () => {
    const runs = splitImageRuns(
      paragraphTokens(
        "[![badge](https://example.com/b.svg)](https://example.com)",
      ),
    );
    expect(runs).toHaveLength(1);
    expect(runs[0].kind).toBe("text");
  });

  it.each([
    ["bold", "**![x](https://example.com/x.png)**"],
    ["italic", "_![x](https://example.com/x.png)_"],
    ["struck", "~~![x](https://example.com/x.png)~~"],
  ])("lifts an image out of %s text", (_name, text) => {
    const runs = splitImageRuns(paragraphTokens(text));
    expect(runs.map((run) => run.kind)).toEqual(["image"]);
  });

  it("keeps the formatting of text around a lifted image", () => {
    const runs = splitImageRuns(
      paragraphTokens("**Before ![x](https://example.com/x.png) after**"),
    );
    expect(runs.map((run) => run.kind)).toEqual(["text", "image", "text"]);
    const [before, , after] = runs;
    for (const run of [before, after]) {
      expect(run.kind === "text" && run.tokens[0].type).toBe("strong");
    }
  });

  it("leaves formatted images nested in links inline", () => {
    const runs = splitImageRuns(
      paragraphTokens(
        "[**![badge](https://example.com/b.svg)**](https://example.com)",
      ),
    );
    expect(runs.map((run) => run.kind)).toEqual(["text"]);
  });

  it("keeps images with mailto URLs inline", () => {
    const runs = splitImageRuns(
      paragraphTokens("Write ![us](mailto:hey@example.com) today"),
    );
    expect(runs.map((run) => run.kind)).toEqual(["text"]);
  });
});

describe("isLoadableImageUrl", () => {
  it.each([
    ["https://example.com/a.png", true],
    ["HTTP://example.com/a.png", true],
    ["mailto:hey@example.com", false],
    ["file:///etc/passwd", false],
    ["not a url", false],
  ])("%s -> %s", (href, expected) => {
    expect(isLoadableImageUrl(href)).toBe(expected);
  });
});
