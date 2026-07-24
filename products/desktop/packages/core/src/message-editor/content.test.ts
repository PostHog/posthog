import { describe, expect, it } from "vitest";
import {
  contentToXml,
  type EditorContent,
  extractFilePaths,
  xmlToContent,
  xmlToPlainText,
} from "./content";

describe("xmlToContent", () => {
  it("parses a file tag into a file chip", () => {
    const result = xmlToContent('<file path="src/foo/bar.ts" />');
    expect(result).toEqual({
      segments: [
        {
          type: "chip",
          chip: { type: "file", id: "src/foo/bar.ts", label: "foo/bar.ts" },
        },
      ],
    });
  });

  it("derives file label from the final path segment when no parent", () => {
    const result = xmlToContent('<file path="README.md" />');
    expect(result.segments).toEqual([
      {
        type: "chip",
        chip: { type: "file", id: "README.md", label: "README.md" },
      },
    ]);
  });

  it("unescapes XML attributes", () => {
    const result = xmlToContent('<file path="a/&quot;weird&quot;.ts" />');
    const segment = result.segments[0];
    expect(segment.type).toBe("chip");
    if (segment.type === "chip") {
      expect(segment.chip.id).toBe('a/"weird".ts');
    }
  });

  it("parses github_issue tags with title", () => {
    const xml =
      '<github_issue number="42" title="Fix bug" url="https://github.com/org/repo/issues/42" />';
    expect(xmlToContent(xml).segments).toEqual([
      {
        type: "chip",
        chip: {
          type: "github_issue",
          id: "https://github.com/org/repo/issues/42",
          label: "#42 - Fix bug",
        },
      },
    ]);
  });

  it("parses github_issue tags without title", () => {
    const xml =
      '<github_issue number="7" url="https://github.com/org/repo/issues/7" />';
    const segment = xmlToContent(xml).segments[0];
    expect(segment.type).toBe("chip");
    if (segment.type === "chip") {
      expect(segment.chip.label).toBe("#7");
    }
  });

  it("parses github_pr tags with title", () => {
    const xml =
      '<github_pr number="123" title="Ship it" url="https://github.com/org/repo/pull/123" />';
    expect(xmlToContent(xml).segments).toEqual([
      {
        type: "chip",
        chip: {
          type: "github_pr",
          id: "https://github.com/org/repo/pull/123",
          label: "#123 - Ship it",
        },
      },
    ]);
  });

  it("serializes a fallback-labeled github_issue chip with an empty title", () => {
    const content: EditorContent = {
      segments: [
        {
          type: "chip",
          chip: {
            type: "github_issue",
            id: "https://github.com/org/repo/issues/1454",
            label: "#1454",
          },
        },
      ],
    };
    expect(contentToXml(content)).toBe(
      '<github_issue number="1454" title="" url="https://github.com/org/repo/issues/1454" />',
    );
  });

  it("round-trips a github_pr chip", () => {
    const content: EditorContent = {
      segments: [
        {
          type: "chip",
          chip: {
            type: "github_pr",
            id: "https://github.com/org/repo/pull/42",
            label: "#42 - Fix thing",
          },
        },
      ],
    };
    expect(xmlToContent(contentToXml(content)).segments).toEqual(
      content.segments,
    );
  });

  it.each([
    ["error", "err-1"],
    ["experiment", "exp-1"],
    ["insight", "ins-1"],
    ["feature_flag", "flag-1"],
  ])("parses %s tag into a chip with id as label", (type, id) => {
    const xml = `<${type} id="${id}" />`;
    expect(xmlToContent(xml).segments).toEqual([
      { type: "chip", chip: { type, id, label: id } },
    ]);
  });

  it("preserves surrounding text around chips", () => {
    const result = xmlToContent(
      'please review <file path="src/a.ts" /> and <file path="src/b.ts" />',
    );
    expect(result.segments).toEqual([
      { type: "text", text: "please review " },
      {
        type: "chip",
        chip: { type: "file", id: "src/a.ts", label: "src/a.ts" },
      },
      { type: "text", text: " and " },
      {
        type: "chip",
        chip: { type: "file", id: "src/b.ts", label: "src/b.ts" },
      },
    ]);
  });

  it("returns a single text segment when no tags are present", () => {
    expect(xmlToContent("just plain text").segments).toEqual([
      { type: "text", text: "just plain text" },
    ]);
  });

  it("returns a single text segment for empty input", () => {
    expect(xmlToContent("").segments).toEqual([{ type: "text", text: "" }]);
  });

  it("parses a folder tag into a folder chip", () => {
    const result = xmlToContent('<folder path="src/foo" />');
    expect(result.segments).toEqual([
      {
        type: "chip",
        chip: { type: "folder", id: "src/foo", label: "src/foo" },
      },
    ]);
  });

  it("round-trips a folder chip", () => {
    const content: EditorContent = {
      segments: [
        {
          type: "chip",
          chip: { type: "folder", id: "src/foo", label: "src/foo" },
        },
      ],
    };
    expect(contentToXml(content)).toBe('<folder path="src/foo" />');
    expect(xmlToContent(contentToXml(content)).segments).toEqual(
      content.segments,
    );
  });

  it("round-trips a local skill command chip", () => {
    const content: EditorContent = {
      segments: [
        {
          type: "chip",
          chip: {
            type: "command",
            id: "/Users/alessandro/.claude/skills/local-skill",
            label: "local-skill",
            skillName: "local-skill",
            skillSource: "user",
            skillPath: "/Users/alessandro/.claude/skills/local-skill",
          },
        },
      ],
    };

    expect(contentToXml(content)).toBe(
      '<skill name="local-skill" source="user" path="/Users/alessandro/.claude/skills/local-skill" />',
    );
    expect(xmlToContent(contentToXml(content)).segments).toEqual(
      content.segments,
    );
  });

  it("extractFilePaths includes folder chips alongside file chips", () => {
    const content: EditorContent = {
      segments: [
        { type: "text", text: "see " },
        {
          type: "chip",
          chip: { type: "folder", id: "src/sub", label: "src/sub" },
        },
        {
          type: "chip",
          chip: { type: "file", id: "src/a.ts", label: "a.ts" },
        },
      ],
    };
    expect(extractFilePaths(content)).toEqual(["src/sub", "src/a.ts"]);
  });

  it("xmlToPlainText renders folder mentions as @mentions", () => {
    expect(
      xmlToPlainText('look at <folder path="products/agentic_tests" /> please'),
    ).toBe("look at @products/agentic_tests please");
  });

  it("xmlToPlainText renders file mentions as @mentions", () => {
    expect(
      xmlToPlainText('see <file path="src/foo/bar.ts" /> for details'),
    ).toBe("see @foo/bar.ts for details");
  });

  it("xmlToPlainText renders structured chip types as @label", () => {
    expect(
      xmlToPlainText(
        'investigate <error id="err-1" /> and <feature_flag id="flag-2" />',
      ),
    ).toBe("investigate @err-1 and @flag-2");
  });

  it("xmlToPlainText leaves plain text untouched", () => {
    expect(xmlToPlainText("ship the fix")).toBe("ship the fix");
  });

  it("xmlToPlainText renders github_pr and github_issue mentions", () => {
    expect(
      xmlToPlainText(
        '<github_pr number="42" title="Add login" url="https://github.com/x/y/pull/42" />',
      ),
    ).toBe("@#42 - Add login");
    expect(
      xmlToPlainText(
        '<github_issue number="7" title="" url="https://github.com/x/y/issues/7" />',
      ),
    ).toBe("@#7");
  });

  it("xmlToPlainText passes through non-chip XML-like text", () => {
    expect(xmlToPlainText("use Array<string> and <div> tags")).toBe(
      "use Array<string> and <div> tags",
    );
  });

  it("round-trips contentToXml for a mix of text and chips", () => {
    const content: EditorContent = {
      segments: [
        { type: "text", text: "look at " },
        {
          type: "chip",
          chip: { type: "file", id: "apps/code/src/a.ts", label: "src/a.ts" },
        },
        { type: "text", text: " and " },
        {
          type: "chip",
          chip: {
            type: "github_issue",
            id: "https://github.com/org/repo/issues/9",
            label: "#9 - Thing",
          },
        },
      ],
    };

    const xml = contentToXml(content);
    const parsed = xmlToContent(xml);
    expect(parsed.segments).toEqual([
      { type: "text", text: "look at " },
      {
        type: "chip",
        chip: { type: "file", id: "apps/code/src/a.ts", label: "src/a.ts" },
      },
      { type: "text", text: " and " },
      {
        type: "chip",
        chip: {
          type: "github_issue",
          id: "https://github.com/org/repo/issues/9",
          label: "#9 - Thing",
        },
      },
    ]);
  });
});
