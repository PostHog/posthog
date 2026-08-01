import { describe, expect, it } from "vitest";
import { parseOpenFence, splitMarkdownBlocks } from "./splitMarkdownBlocks";

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
