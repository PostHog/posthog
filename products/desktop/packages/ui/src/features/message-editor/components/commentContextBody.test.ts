import { describe, expect, it } from "vitest";
import { parseCommentContextBody } from "./commentContextBody";

describe("parseCommentContextBody", () => {
  it.each([
    {
      name: "a quoted selection",
      body: "- **Page** /pricing\n> Save 20%\n> on yearly plans",
      expected: { quote: "Save 20%\non yearly plans", snippet: null },
    },
    {
      name: "a code snippet inside a longer fence",
      body: "````html\n<button>\n```\n</button>\n````",
      expected: { quote: null, snippet: "<button>\n```\n</button>" },
    },
    {
      name: "a quote marker inside the snippet",
      body: "```\n> not a quote\n```",
      expected: { quote: null, snippet: "> not a quote" },
    },
    {
      name: "plain comment text",
      body: "Make this button bigger",
      expected: { quote: null, snippet: null },
    },
  ])("reads $name", ({ body, expected }) => {
    expect(parseCommentContextBody(body)).toEqual(expected);
  });
});
