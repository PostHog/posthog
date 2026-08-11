import { describe, expect, it } from "vitest";
import {
  markOpenLinkDestination,
  maskOpenLinkDestination,
  parseOpenFence,
  splitMarkdownBlocks,
} from "./splitMarkdownBlocks";

describe("splitMarkdownBlocks", () => {
  it.each([
    "",
    "single line",
    "para one\n\npara two\n\npara three",
    "# Heading\n\nText with **bold**.\n\n- a\n- b\n",
    "Intro\n\n```ts\nconst x = 1;\nconst y = 2;\n```\n\nOutro",
    "Intro\n\n~~~ts\nconst x = 1;\n~~~\n\nOutro",
    "trailing blanks\n\n\n\n",
  ])("joins back to the exact input, dropping no text: %j", (src) => {
    expect(splitMarkdownBlocks(src).join("")).toBe(src);
  });

  it("splits paragraphs at blank lines", () => {
    expect(splitMarkdownBlocks("a\n\nb\n\nc")).toEqual(["a\n\n", "b\n\n", "c"]);
  });

  it("keeps a fenced code block (with blank lines inside) as one block", () => {
    const md = "```\nline1\n\nline2\n```\n\nafter";
    expect(splitMarkdownBlocks(md)).toEqual([
      "```\nline1\n\nline2\n```\n\n",
      "after",
    ]);
  });

  it("keeps a tilde-fenced block (with blank lines inside) as one block", () => {
    const md = "~~~\nline1\n\nline2\n~~~\n\nafter";
    expect(splitMarkdownBlocks(md)).toEqual([
      "~~~\nline1\n\nline2\n~~~\n\n",
      "after",
    ]);
  });

  it("does not let a ```lang content line close the fence early", () => {
    // ```end carries trailing text, so it is content, not a close. The blank
    // line after it must stay inside the still-open fence.
    const md = "```ts\nconst a = 1;\n```end\n\nstill code\n```\n\nafter";
    expect(splitMarkdownBlocks(md)).toEqual([
      "```ts\nconst a = 1;\n```end\n\nstill code\n```\n\n",
      "after",
    ]);
  });

  it("does not let an inner shorter fence close an outer longer one", () => {
    const md = "````md\nintro\n\n```ts\nx = 1\n```\n````\n\nafter";
    expect(splitMarkdownBlocks(md)).toEqual([
      "````md\nintro\n\n```ts\nx = 1\n```\n````\n\n",
      "after",
    ]);
  });

  it("treats a fence indented up to 3 spaces as a fence", () => {
    const md = " ```\ncode\n\nmore\n ```\n\nafter";
    expect(splitMarkdownBlocks(md)).toEqual([
      " ```\ncode\n\nmore\n ```\n\n",
      "after",
    ]);
  });

  it("does not split inside an unterminated fence (the tail stays whole)", () => {
    const md = "intro\n\n```ts\nconst a = 1;\n\nconst b = 2;";
    const blocks = splitMarkdownBlocks(md);
    expect(blocks[blocks.length - 1]).toContain("const b = 2;");
    expect(blocks.join("")).toBe(md);
  });
});

describe("parseOpenFence", () => {
  it("returns null when the block has no fence", () => {
    expect(parseOpenFence("just text\n\nmore text")).toBeNull();
  });

  it("returns null when every fence in the block is already closed", () => {
    expect(parseOpenFence("```ts\ndone\n```")).toBeNull();
  });

  it("splits the prose before the open fence from the code so far", () => {
    expect(parseOpenFence("Here:\n```ts\nconst a = 1;")).toEqual({
      before: "Here:\n",
      code: "const a = 1;",
    });
  });

  it("returns empty before when the block opens with the fence", () => {
    expect(parseOpenFence("```ts\nconst x = 1;")).toEqual({
      before: "",
      code: "const x = 1;",
    });
  });

  it("returns empty code when the open marker has no trailing newline yet", () => {
    expect(parseOpenFence("```ts")).toEqual({ before: "", code: "" });
  });

  it("parses a tilde open fence", () => {
    expect(parseOpenFence("~~~\nx")).toEqual({ before: "", code: "x" });
  });

  it("targets the LAST open fence, leaving an earlier completed fence in `before`", () => {
    // A completed fence, then text, then an open fence, all one block (no blank
    // lines). The earlier fence must not be swallowed into plain text.
    const block = "```ts\ndone\n```\ntext\n```ts\npartial";
    expect(parseOpenFence(block)).toEqual({
      before: "```ts\ndone\n```\ntext\n",
      code: "partial",
    });
  });
});

describe("maskOpenLinkDestination", () => {
  it("shows the label while hiding an incomplete destination", () => {
    expect(
      maskOpenLinkDestination(
        "Download [the report](https://example.com/a-very-long?token=secret",
      ),
    ).toBe("Download the report");
  });

  it("leaves a completed link unchanged", () => {
    const markdown = "Download [the report](https://example.com/report) now";
    expect(maskOpenLinkDestination(markdown)).toBe(markdown);
  });

  it("waits for nested destination parentheses to close", () => {
    expect(maskOpenLinkDestination("See [docs](https://example.com/a(b)")).toBe(
      "See docs",
    );
  });

  it("ignores link syntax inside inline code", () => {
    const markdown = "`[label](https://example.com/incomplete`";
    expect(maskOpenLinkDestination(markdown)).toBe(markdown);
  });

  it("treats an unmatched backtick as literal text", () => {
    expect(
      maskOpenLinkDestination(
        "Unmatched ` then [report](https://example.com/private",
      ),
    ).toBe("Unmatched ` then report");
  });

  it("supports nested brackets and escaped destination parentheses", () => {
    expect(
      maskOpenLinkDestination("See [the [new] docs](https://example.com/a\\("),
    ).toBe("See the [new] docs");
  });

  it("shows image alt text while hiding an incomplete destination", () => {
    expect(
      maskOpenLinkDestination("Preview: ![chart](https://example.com/ch"),
    ).toBe("Preview: chart");
  });

  it("masks the destination at every streaming boundary", () => {
    const markdown =
      "Download [the report](https://example.com/report?token=secret)";
    const destinationStart = markdown.indexOf("https://");

    for (let end = destinationStart; end < markdown.length; end++) {
      const rendered = maskOpenLinkDestination(markdown.slice(0, end));
      expect(rendered).not.toContain("example.com");
      expect(rendered).not.toContain("token=secret");
    }

    expect(maskOpenLinkDestination(markdown)).toBe(markdown);
  });

  it("does not treat an escaped exclamation mark as an image marker", () => {
    expect(
      maskOpenLinkDestination("\\![label](https://example.com/incomplete"),
    ).toBe("\\!label");
  });

  it("handles angle-bracket destinations containing parentheses", () => {
    const complete = "[docs](<https://example.com/a(b>)";
    expect(maskOpenLinkDestination(complete)).toBe(complete);
    expect(maskOpenLinkDestination("[docs](<https://example.com/a(b>")).toBe(
      "docs",
    );
  });

  it.each([
    '[docs](https://example.com "a title")',
    "[docs](https://example.com 'a title')",
    "[docs](https://example.com (a title))",
    '[docs](<https://example.com/a(b)> "a title")',
  ])("recognizes a completed destination with a title: %s", (markdown) => {
    expect(maskOpenLinkDestination(markdown)).toBe(markdown);
  });

  it.each([
    '[docs](https://example.com "an unfinished title',
    "[docs](https://example.com (an unfinished title)",
    '[docs](<https://example.com/a(b)> "title"',
  ])("masks an incomplete destination or title: %s", (markdown) => {
    expect(maskOpenLinkDestination(markdown)).toBe("docs");
  });
});

describe("markOpenLinkDestination", () => {
  it("replaces an incomplete destination with a renderable pending link", () => {
    expect(
      markOpenLinkDestination(
        "Here is [the file](https://example.com/long",
        "#pending",
      ),
    ).toBe("Here is [the file](#pending)");
  });

  it("leaves a completed link unchanged", () => {
    const markdown = "Here is [the file](https://example.com/file)";
    expect(markOpenLinkDestination(markdown, "#pending")).toBe(markdown);
  });
});
