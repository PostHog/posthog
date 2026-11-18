import { describe, expect, it } from "vitest";
import { convertClipboardHtml, htmlToMarkdown } from "./htmlToMarkdown";

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

  it.each([
    [
      "a standalone code block as plain text",
      '<div class="selection"><pre><code><span>const x = 1;</span></code></pre></div>',
      "const x = 1;",
      { text: "const x = 1;", kind: "plain" },
    ],
    [
      "a code block with surrounding prose as markdown",
      "<p>Example:</p><pre><code>const x = 1;</code></pre>",
      "Example:\nconst x = 1;",
      { text: "Example:\n\n```\nconst x = 1;\n```", kind: "markdown" },
    ],
    [
      "a code block with preceding prose in the same wrapper as markdown",
      "<div>Example:<pre><code>const x = 1;</code></pre></div>",
      "Example:\nconst x = 1;",
      { text: "Example:\n\n```\nconst x = 1;\n```", kind: "markdown" },
    ],
    [
      "a code block with following prose in the same wrapper as markdown",
      "<div><pre><code>const x = 1;</code></pre>Done.</div>",
      "const x = 1;\nDone.",
      { text: "```\nconst x = 1;\n```\n\nDone.", kind: "markdown" },
    ],
    [
      "a code block without a plain-text payload as markdown",
      "<pre><code>const x = 1;</code></pre>",
      "",
      { text: "```\nconst x = 1;\n```", kind: "markdown" },
    ],
  ])("converts %s", (_name, html, plainText, expected) => {
    expect(convertClipboardHtml(html, plainText)).toEqual(expected);
  });
});
