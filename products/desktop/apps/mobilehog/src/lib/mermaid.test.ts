import { describe, expect, it } from "vitest";
import {
  hasRemoteImageNode,
  isClosedFence,
  isMermaidLang,
  mermaidHtml,
  parseMermaidMessage,
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
    const html = mermaidHtml('graph TD\n  A["</script><img src=x>"]', false);
    expect(html.match(/<\/script>/g)).toHaveLength(1);
    expect(html).toContain("\\u003c/script>\\u003cimg src=x>");
  });

  it("uses strict security and follows the color scheme", () => {
    expect(mermaidHtml("graph TD", true)).toContain('"theme":"dark"');
    expect(mermaidHtml("graph TD", false)).toContain('"theme":"default"');
    expect(mermaidHtml("graph TD", false)).toContain(
      '"securityLevel":"strict"',
    );
  });

  it("blocks every network fetch", () => {
    expect(mermaidHtml("graph TD", false)).toContain("default-src 'none'");
  });
});
