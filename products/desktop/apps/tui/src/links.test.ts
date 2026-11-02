import { hyperlink } from "@earendil-works/pi-tui";
import { describe, expect, it } from "vitest";
import { linkAt } from "./links";

const BLUE = (text: string): string => `\u001b[34m${text}\u001b[39m`;

describe("linkAt", () => {
  it.each([
    [
      "the text of an OSC 8 hyperlink",
      `See ${hyperlink(BLUE("the docs"), "https://posthog.com/docs")} now`,
      6,
      "https://posthog.com/docs",
    ],
    [
      "text next to an OSC 8 hyperlink",
      `See ${hyperlink("the docs", "https://posthog.com/docs")} now`,
      13,
      null,
    ],
    [
      "a URL written out in the text",
      `PR: ${BLUE("https://github.com/PostHog/posthog/pull/1")}`,
      10,
      "https://github.com/PostHog/posthog/pull/1",
    ],
    [
      "a URL in brackets, without the closing bracket or full stop",
      "the docs (https://posthog.com/docs).",
      20,
      "https://posthog.com/docs",
    ],
    ["the full stop after a URL", "at https://posthog.com.", 22, null],
    [
      "a URL with its own brackets",
      "https://en.wikipedia.org/wiki/Hog_(animal)",
      5,
      "https://en.wikipedia.org/wiki/Hog_(animal)",
    ],
    [
      "a URL after wide characters, by cell rather than character",
      "猪猪 https://posthog.com",
      5,
      "https://posthog.com",
    ],
    [
      "a hyperlink to a local file",
      hyperlink("notes", "file:///etc/passwd"),
      1,
      null,
    ],
    [
      "a hyperlink to an app scheme",
      hyperlink("open", "vscode://file/tmp/x"),
      1,
      null,
    ],
  ])("%s", (_, line, column, expected) => {
    expect(linkAt(line, column)).toBe(expected);
  });
});
