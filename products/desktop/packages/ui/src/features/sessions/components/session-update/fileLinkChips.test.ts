import { describe, expect, it } from "vitest";
import { parseMarkdownFileHref } from "./fileLinkChips";

describe("parseMarkdownFileHref", () => {
  it.each([
    [
      "/tmp/workspace/repos/posthog/posthog/frontend/src/app.tsx",
      "/tmp/workspace/repos/posthog/posthog/frontend/src/app.tsx",
    ],
    ["/tmp/workspace/My%20Report.md:12", "/tmp/workspace/My Report.md:12"],
    ["frontend/src/app.tsx#L42-L45", "frontend/src/app.tsx:42-45"],
    ["README.md", "README.md"],
  ])("recognizes file href %s", (href, expected) => {
    expect(parseMarkdownFileHref(href)).toBe(expected);
  });

  it.each(["https://posthog.com/docs", "mailto:test@example.com", "#section"])(
    "ignores non-file href %s",
    (href) => {
      expect(parseMarkdownFileHref(href)).toBeNull();
    },
  );
});
