import { describe, expect, it } from "vitest";
import { htmlToMarkdown } from "./htmlToMarkdown";

describe("htmlToMarkdown", () => {
  it.each([
    [
      "headings, emphasis and links",
      "<h1>Title</h1><p>Some <strong>bold</strong> and <em>italic</em> with a <a href='https://posthog.com'>link</a>.</p>",
      "# Title\n\nSome **bold** and *italic* with a [link](https://posthog.com).",
    ],
    [
      "unordered lists",
      "<ul><li>one</li><li>two</li></ul>",
      "-   one\n-   two",
    ],
    [
      "tables via the gfm plugin",
      "<table><thead><tr><th>a</th><th>b</th></tr></thead><tbody><tr><td>1</td><td>2</td></tr></tbody></table>",
      "| a   | b   |\n| --- | --- |\n| 1   | 2   |",
    ],
    [
      "fenced code blocks",
      "<pre><code>const x = 1;</code></pre>",
      "```\nconst x = 1;\n```",
    ],
  ])("converts %s", (_, html, expected) => {
    expect(htmlToMarkdown(html)).toBe(expected);
  });

  it("returns null when there is no formatting beyond the plain-text fallback", () => {
    const html = "<p>just text</p>";
    expect(htmlToMarkdown(html, "just text")).toBeNull();
  });

  it("returns null for empty html", () => {
    expect(htmlToMarkdown("")).toBeNull();
    expect(htmlToMarkdown("<p></p>")).toBeNull();
  });

  it.each([
    ["ordered-list-style numbers", "1. First 2. Second"],
    ["underscores in identifiers", "call snake_case_name here"],
    ["square brackets", "an array like arr[0] and [x]"],
    ["leading hash and dash", "# not a heading - not a bullet"],
  ])(
    "does not backslash-escape plain text (%s), so it defers to native paste",
    (_, text) => {
      // Plain punctuation must not be mangled into "1\\.", "snake\\_case", etc.
      // When it stays intact it equals the plain-text fallback and returns null.
      expect(htmlToMarkdown(`<span>${text}</span>`, text)).toBeNull();
    },
  );

  it("strips macOS <style> clipboard blocks instead of leaking CSS as text", () => {
    // Shape of the text/html macOS puts on the clipboard when copying rich
    // text from native apps. The CSS must not survive into the paste.
    const html = [
      '<meta charset="utf-8">',
      "<style>",
      "<!--",
      "p.p1 {margin: 0.0px 0.0px 0.0px 0.0px; font: 18.0px Helvetica}",
      "-->",
      "</style>",
      '<p class="p1">Yo dude</p>',
    ].join("\n");
    // No formatting beyond the plain text once the CSS is gone, so it defers.
    expect(htmlToMarkdown(html, "Yo dude")).toBeNull();
    expect(htmlToMarkdown(html)).toBe("Yo dude");
  });

  it("preserves real formatting without escaping surrounding punctuation", () => {
    const html = "<p>See <strong>item_1.</strong> in arr[0]</p>";
    expect(htmlToMarkdown(html, "See item_1. in arr[0]")).toBe(
      "See **item_1.** in arr[0]",
    );
  });
});
