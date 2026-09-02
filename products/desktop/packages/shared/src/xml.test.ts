import { describe, expect, it } from "vitest";
import { escapeXmlAttr, unescapeXmlAttr } from "./xml";

describe("escapeXmlAttr", () => {
  it("escapes the five XML attribute metacharacters", () => {
    expect(escapeXmlAttr(`&<>"'`)).toBe("&amp;&lt;&gt;&quot;&apos;");
  });

  it("escapes ampersands before other entities so output is not double-escaped on reverse", () => {
    expect(escapeXmlAttr("a & b")).toBe("a &amp; b");
  });

  it("leaves plain text untouched", () => {
    expect(escapeXmlAttr("hello world")).toBe("hello world");
  });
});

describe("unescapeXmlAttr", () => {
  it("reverses the five entities", () => {
    expect(unescapeXmlAttr("&amp;&lt;&gt;&quot;&apos;")).toBe(`&<>"'`);
  });
});

describe("escape/unescape round-trip", () => {
  it.each([
    `&<>"'`,
    `tag <a href="x">y</a>`,
    "literal &amp; entity",
    "ampersands & < mixed > with \" quotes ' and more",
    "plain",
  ])("round-trips %j", (input) => {
    expect(unescapeXmlAttr(escapeXmlAttr(input))).toBe(input);
  });
});
