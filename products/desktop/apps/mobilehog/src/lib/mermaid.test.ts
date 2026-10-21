import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { runInNewContext } from "node:vm";
import { describe, expect, it } from "vitest";
import {
  type DiagramSize,
  hasRemoteImageNode,
  inlineScriptSource,
  isClosedFence,
  isMermaidLang,
  mermaidHtml,
  parseMermaidMessage,
  rememberSize,
} from "./mermaid";

describe("isMermaidLang", () => {
  it.each([
    ["mermaid", true],
    ["Mermaid", true],
    ["mermaid title", true],
    ["mermaidjs", false],
    ["ts", false],
    [undefined, false],
  ])("%s -> %s", (lang, expected) => {
    expect(isMermaidLang(lang)).toBe(expected);
  });
});

describe("isClosedFence", () => {
  it.each([
    ["```mermaid\ngraph TD\n```", true],
    ["```mermaid\ngraph TD\n```\n\n", true],
    ["~~~mermaid\ngraph TD\n~~~", true],
    ["````mermaid\ngraph TD\n````", true],
    ["```mermaid\ngraph TD\n  A-->B", false],
    ["```mermaid\ngraph TD\n~~~", false],
    ["````mermaid\ngraph TD\n```", false],
    ["```mermaid", false],
  ])("%j -> %s", (raw, expected) => {
    expect(isClosedFence(raw)).toBe(expected);
  });
});

describe("hasRemoteImageNode", () => {
  it.each([
    ['flowchart TD\n  A@{ img: "https://example.com/a.png" }', true],
    ["flowchart TD\n  A@{ IMG: 'https://example.com/a.png' }", true],
    ["flowchart TD\n  A@{ label: x, img: //example.com/a.png }", true],
    ['flowchart TD\n  A@{ img: "data:image/png;base64,AAAA" }', false],
    ["flowchart TD\n  A[img] --> B", false],
  ])("%j -> %s", (code, expected) => {
    expect(hasRemoteImageNode(code)).toBe(expected);
  });
});

describe("parseMermaidMessage", () => {
  it.each([
    [
      '{"type":"size","width":120,"height":80}',
      { type: "size", width: 120, height: 80 },
    ],
    ['{"type":"error"}', { type: "error" }],
    ['{"type":"size","width":0,"height":80}', null],
    ['{"type":"size","width":"120","height":80}', null],
    ["not json", null],
    ["null", null],
  ])("%s", (data, expected) => {
    expect(parseMermaidMessage(data)).toEqual(expected);
  });
});

describe("mermaidHtml", () => {
  it("keeps diagram text from closing the script tag", () => {
    const html = mermaidHtml(
      'graph TD\n  A["</script><img src=x>"]',
      false,
      "",
    );
    expect(html.match(/<\/script>/g)).toHaveLength(2);
    expect(html).toContain("\\u003c/script>\\u003cimg src=x>");
  });

  it("uses strict security and follows the color scheme", () => {
    expect(mermaidHtml("graph TD", true, "")).toContain('"theme":"dark"');
    expect(mermaidHtml("graph TD", false, "")).toContain('"theme":"default"');
    expect(mermaidHtml("graph TD", false, "")).toContain(
      '"securityLevel":"strict"',
    );
  });

  it("blocks every network fetch", () => {
    expect(mermaidHtml("graph TD", false, "")).toContain("default-src 'none'");
  });

  it("loads the bundle in a page script before the render script", () => {
    const html = mermaidHtml("graph TD", false, "window.mermaid = {};");
    expect(html).toContain("<script>window.mermaid = {};</script>");
    expect(html.indexOf("window.mermaid = {};")).toBeLessThan(
      html.indexOf("mermaid.initialize"),
    );
  });
});

describe("inlineScriptSource", () => {
  it("escapes sequences that end or nest a script tag", () => {
    const source = 'a="</script>";b=/<!--/;c="<SCRIPT>";d="a<b"';
    const escaped = inlineScriptSource(source);
    expect(escaped).not.toMatch(/<\/?script|<!--/i);
    expect(escaped).toContain('d="a<b"');
    const context = runInNewContext(
      `${escaped};({ a, b: b.test("<!--"), c, d })`,
    );
    expect(context).toEqual({
      a: "</script>",
      b: true,
      c: "<SCRIPT>",
      d: "a<b",
    });
  });

  it("keeps the real bundle runnable as a page script", () => {
    const path = createRequire(import.meta.url).resolve(
      "mermaid/dist/mermaid.min.js",
    );
    const source = inlineScriptSource(readFileSync(path, "utf8"));
    expect(source).not.toMatch(/<\/script/i);
    const context: Record<string, unknown> = {};
    runInNewContext(source, context);
    expect(context.mermaid).toBeDefined();
  });
});

describe("rememberSize", () => {
  const size = (width: number): DiagramSize => ({ width, height: 10 });

  it("drops the least recently stored entries over the limit", () => {
    const cache = new Map<string, DiagramSize>();
    rememberSize(cache, "a", size(1), 2);
    rememberSize(cache, "b", size(2), 2);
    rememberSize(cache, "a", size(3), 2);
    rememberSize(cache, "c", size(4), 2);
    expect([...cache.keys()]).toEqual(["a", "c"]);
    expect(cache.get("a")).toEqual(size(3));
  });
});
