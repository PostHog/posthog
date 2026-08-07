import { describe, expect, it } from "vitest";
import { type LinkSegment, splitLinkSegments } from "./linkify";

const text = (t: string): LinkSegment => ({ type: "text", text: t });
const link = (url: string): LinkSegment => ({
  type: "link",
  text: url,
  href: url,
});

describe("splitLinkSegments", () => {
  it.each<[string, string, LinkSegment[]]>([
    ["plain text", "no links here", [text("no links here")]],
    ["bare url", "https://posthog.com", [link("https://posthog.com")]],
    [
      "url mid-sentence",
      "see https://posthog.com for docs",
      [text("see "), link("https://posthog.com"), text(" for docs")],
    ],
    [
      "http url",
      "http://example.com/a?b=c#d",
      [link("http://example.com/a?b=c#d")],
    ],
    [
      "multiple urls",
      "https://a.com and https://b.com",
      [link("https://a.com"), text(" and "), link("https://b.com")],
    ],
    [
      "trailing period stays prose",
      "read https://posthog.com/docs.",
      [text("read "), link("https://posthog.com/docs"), text(".")],
    ],
    [
      "trailing comma and question mark",
      "https://a.com, or https://b.com?",
      [link("https://a.com"), text(", or "), link("https://b.com"), text("?")],
    ],
    [
      "wrapping parens stay prose",
      "(https://posthog.com)",
      [text("("), link("https://posthog.com"), text(")")],
    ],
    [
      "paren inside url is kept",
      "https://en.wikipedia.org/wiki/A_(B)",
      [link("https://en.wikipedia.org/wiki/A_(B)")],
    ],
    [
      "url split across whitespace",
      "https://a.com\nhttps://b.com",
      [link("https://a.com"), text("\n"), link("https://b.com")],
    ],
    ["not a url scheme", "ftp://example.com", [text("ftp://example.com")]],
    ["empty string", "", []],
    [
      "markdown link uses its label",
      "[Signups](https://us.posthog.com/code/canvas/c/d) has been created",
      [
        {
          type: "link",
          text: "Signups",
          href: "https://us.posthog.com/code/canvas/c/d",
        },
        text(" has been created"),
      ],
    ],
    [
      "markdown link alongside a bare url",
      "see [docs](https://a.com) or https://b.com",
      [
        text("see "),
        { type: "link", text: "docs", href: "https://a.com" },
        text(" or "),
        link("https://b.com"),
      ],
    ],
    [
      "markdown label without a url stays prose",
      "[not a link](just text)",
      [text("[not a link](just text)")],
    ],
  ])("%s", (_label, input, expected) => {
    expect(splitLinkSegments(input)).toEqual(expected);
  });
});
