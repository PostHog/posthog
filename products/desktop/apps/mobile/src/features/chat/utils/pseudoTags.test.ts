import { describe, expect, it } from "vitest";
import {
  isDesktopLocalPath,
  type PseudoTagSegment,
  parsePseudoTags,
} from "./pseudoTags";

const PR_TAG =
  '<github_pr number="123" title="Ship it" url="https://github.com/org/repo/pull/123" />';

describe("isDesktopLocalPath", () => {
  it.each([
    ["/var/folders/xy/T/report.md", true],
    ["/private/var/tmp/scratch.txt", true],
    ["/Users/vasco/code/app.ts", true],
    ["/home/vasco/code/app.ts", true],
    ["/tmp/a.ts", true],
    ["~/notes/todo.md", true],
    ["C:\\Users\\vasco\\app.ts", true],
    ["src/features/chat/index.ts", false],
    ["/srv/app/main.go", false],
    ["/variants/a.ts", false],
    ["", false],
  ])("classifies %s as desktop-local=%s", (path, expected) => {
    expect(isDesktopLocalPath(path)).toBe(expected);
  });
});

describe("parsePseudoTags", () => {
  it("returns a single text segment for text with no tags", () => {
    expect(parsePseudoTags("just a plain message")).toEqual([
      { type: "text", text: "just a plain message" },
    ]);
  });

  it("renders a file tag as a chip and keeps the surrounding text", () => {
    expect(
      parsePseudoTags('please review <file path="src/a.ts" /> today'),
    ).toEqual<PseudoTagSegment[]>([
      { type: "text", text: "please review " },
      { type: "file", path: "src/a.ts", label: "src/a.ts", fromDesktop: false },
      { type: "text", text: " today" },
    ]);
  });

  it("flags desktop-local file paths so the chip can say where they came from", () => {
    const [segment] = parsePseudoTags(
      '<file path="/var/folders/xy/T/out.md" />',
    );
    expect(segment).toEqual({
      type: "file",
      path: "/var/folders/xy/T/out.md",
      label: "T/out.md",
      fromDesktop: true,
    });
  });

  it("renders a github_pr tag as a tappable chip labelled with its title", () => {
    expect(parsePseudoTags(PR_TAG)).toEqual<PseudoTagSegment[]>([
      {
        type: "github",
        kind: "pr",
        url: "https://github.com/org/repo/pull/123",
        label: "#123 - Ship it",
      },
    ]);
  });

  it("labels a titleless github_pr tag with just its number", () => {
    expect(
      parsePseudoTags(
        '<github_pr number="42" title="" url="https://github.com/org/repo/pull/42" />',
      ),
    ).toEqual<PseudoTagSegment[]>([
      {
        type: "github",
        kind: "pr",
        url: "https://github.com/org/repo/pull/42",
        label: "#42",
      },
    ]);
  });

  it("renders a github_issue tag as an issue chip", () => {
    const [segment] = parsePseudoTags(
      '<github_issue number="7" title="Bug" url="https://github.com/org/repo/issues/7" />',
    );
    expect(segment).toMatchObject({ type: "github", kind: "issue" });
  });

  it("unescapes xml entities in attributes", () => {
    expect(
      parsePseudoTags(
        '<github_pr number="1" title="Fix &quot;login&quot; &amp; redirect" url="https://github.com/org/repo/pull/1" />',
      ),
    ).toEqual<PseudoTagSegment[]>([
      {
        type: "github",
        kind: "pr",
        url: "https://github.com/org/repo/pull/1",
        label: '#1 - Fix "login" & redirect',
      },
    ]);
  });

  it("handles multiple tags across a multiline description", () => {
    const text = [
      "Compare the two runs:",
      "",
      `1. ${PR_TAG}`,
      '2. <file path="/Users/vasco/repo/src/b.ts" />',
      "",
      "Then summarise.",
    ].join("\n");

    expect(parsePseudoTags(text)).toEqual<PseudoTagSegment[]>([
      { type: "text", text: "Compare the two runs:\n\n1. " },
      {
        type: "github",
        kind: "pr",
        url: "https://github.com/org/repo/pull/123",
        label: "#123 - Ship it",
      },
      { type: "text", text: "\n2. " },
      {
        type: "file",
        path: "/Users/vasco/repo/src/b.ts",
        label: "src/b.ts",
        fromDesktop: true,
      },
      { type: "text", text: "\n\nThen summarise." },
    ]);
  });

  it("renders a folder tag as a file chip", () => {
    const [segment] = parsePseudoTags(
      '<folder path="/Users/vasco/repo/src" />',
    );
    expect(segment).toMatchObject({
      type: "file",
      path: "/Users/vasco/repo/src",
    });
  });

  it.each([
    ["unclosed tag", '<file path="src/a.ts">'],
    ["missing slash", '<file path="src/a.ts" >'],
    ["no attributes", "<file />"],
    ["unquoted attribute", "<file path=src/a.ts />"],
    ["unknown tag", '<mystery path="src/a.ts" />'],
    ["bare angle brackets", "a < b and c > d"],
    [
      "github tag with neither number nor url",
      '<github_pr title="Incomplete" />',
    ],
  ])("leaves %s as raw text rather than dropping it", (_name, text) => {
    expect(parsePseudoTags(text)).toEqual([{ type: "text", text }]);
  });

  it("keeps a github tag with an unsafe url as plain text", () => {
    expect(
      parsePseudoTags(
        '<github_pr number="12" title="Unsafe" url="javascript:alert(1)" />',
      ),
    ).toEqual([{ type: "text", text: "#12 - Unsafe" }]);
  });

  it("merges text around a dropped tag so markdown spanning it still parses", () => {
    expect(parsePseudoTags('**bold <error id="e1" /> bold**')).toEqual([
      { type: "text", text: "**bold @e1 bold**" },
    ]);
  });

  it("renders a skill tag as its slash command", () => {
    expect(
      parsePseudoTags(
        'run <skill name="review" source="user" path="/skills/review/SKILL.md" />',
      ),
    ).toEqual([{ type: "text", text: "run /review" }]);
  });

  it("returns no segments for empty text", () => {
    expect(parsePseudoTags("")).toEqual([]);
  });
});
