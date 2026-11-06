import { describe, expect, it } from "vitest";
import {
  applyCspToHtml,
  buildCspMetaTag,
  buildCspString,
  escapeAttr,
} from "./csp";

describe("declared origins", () => {
  it.each([
    "example.com",
    "*.example.com",
    "example.com:8080",
    "https://cdn.example.com",
    "https://*.cloudflare.com",
    "wss://api.example.com",
    "http://localhost:8787",
    // A fully qualified name keeps its root dot under the host-source grammar.
    "cdn.example.com.",
    "https://cdn.example.com.",
  ])("reaches the policy intact: %j", (source) => {
    expect(buildCspString({ resourceDomains: [source] })).toContain(
      `script-src 'self' 'unsafe-inline' ${source}`,
    );
  });

  it.each([
    "' unsafe-eval; script-src *;",
    '" onload=alert(1)',
    "example .com",
    "'self'",
    "https:",
    // One root dot is allowed, so guard against loosening that to any number.
    "example.com..",
  ])("is dropped rather than edited to fit: %j", (source) => {
    // Editing it down to fit would grant an origin nobody declared.
    expect(buildCspString({ resourceDomains: [source] })).toContain(
      "script-src 'self' 'unsafe-inline';",
    );
  });

  it("keeps the origins declared beside an invalid one", () => {
    expect(
      buildCspString({
        resourceDomains: ["https://cdn.example.com", "example .com"],
      }),
    ).toContain("script-src 'self' 'unsafe-inline' https://cdn.example.com;");
  });
});

describe("buildCspString", () => {
  it.each([
    ["default-src 'none'"],
    ["script-src 'self' 'unsafe-inline'"],
    ["style-src 'self' 'unsafe-inline'"],
    ["img-src 'self' data:"],
    ["media-src 'self' data:"],
    ["connect-src 'none'"],
    ["frame-src 'none'"],
    ["form-action 'none'"],
    ["base-uri 'none'"],
    ["object-src 'none'"],
  ])("default policy contains %s", (directive) => {
    expect(buildCspString()).toContain(directive);
  });

  it.each([
    ["connect-src 'none'"],
    ["frame-src 'none'"],
    ["form-action 'none'"],
    ["base-uri 'none'"],
    ["img-src 'self' data:"],
  ])("uses the restrictive default %s for empty metadata", (directive) => {
    expect(buildCspString({})).toContain(directive);
  });

  it("maps connectDomains to connect-src", () => {
    expect(
      buildCspString({
        connectDomains: ["api.example.com", "*.cdn.example.com"],
      }),
    ).toContain("connect-src api.example.com *.cdn.example.com");
  });

  it("maps resourceDomains to img/media/font/script/style-src", () => {
    const result = buildCspString({ resourceDomains: ["cdn.example.com"] });
    expect(result).toContain("img-src 'self' data: cdn.example.com");
    expect(result).toContain("media-src 'self' data: cdn.example.com");
    expect(result).toContain("font-src cdn.example.com");
    expect(result).toContain(
      "script-src 'self' 'unsafe-inline' cdn.example.com",
    );
    expect(result).toContain(
      "style-src 'self' 'unsafe-inline' cdn.example.com",
    );
  });

  it("omits resourceDomains from script/style-src when not declared", () => {
    const result = buildCspString({});
    expect(result).toContain("script-src 'self' 'unsafe-inline'");
    expect(result).not.toMatch(/script-src 'self' 'unsafe-inline' ;/);
  });

  it("maps frameDomains to frame-src", () => {
    expect(buildCspString({ frameDomains: ["embed.example.com"] })).toContain(
      "frame-src embed.example.com",
    );
  });

  it("maps baseUriDomains to base-uri", () => {
    expect(buildCspString({ baseUriDomains: ["example.com"] })).toContain(
      "base-uri example.com",
    );
  });

  it("always includes form-action 'none'", () => {
    expect(buildCspString({ connectDomains: ["api.example.com"] })).toContain(
      "form-action 'none'",
    );
  });

  it("drops a domain that tries to inject a directive", () => {
    const result = buildCspString({
      connectDomains: ["example.com; script-src 'unsafe-eval'"],
    });
    expect(result).toContain("connect-src 'none'");
    expect(result).not.toMatch(/;\s*script-src\s+'unsafe-eval'/);
  });
});

describe("escapeAttr", () => {
  it.each([
    ['hello "world"', "hello &quot;world&quot;"],
    ["hello 'world'", "hello &#39;world&#39;"],
    ["a & b", "a &amp; b"],
    ["<script>alert(1)</script>", "&lt;script&gt;alert(1)&lt;/script&gt;"],
    ["default-src none", "default-src none"],
  ])("escapes %j", (input, expected) => {
    expect(escapeAttr(input)).toBe(expected);
  });
});

describe("buildCspMetaTag", () => {
  it("returns a valid meta tag with the default policy", () => {
    const tag = buildCspMetaTag();
    expect(tag).toMatch(
      /^<meta http-equiv="Content-Security-Policy" content=".*">$/,
    );
    expect(tag).toContain("default-src");
  });

  it("escapes the CSP content in the attribute", () => {
    const tag = buildCspMetaTag({ connectDomains: ["example.com"] });
    expect(tag).toContain("connect-src example.com");
    expect(tag).toMatch(/content="[^"]+"/);
  });
});

describe("applyCspToHtml", () => {
  it("prepends the CSP meta when there is no doctype", () => {
    const out = applyCspToHtml("<html><body>hi</body></html>");
    expect(out.startsWith(buildCspMetaTag())).toBe(true);
  });

  it("inserts the CSP meta after a leading doctype", () => {
    const out = applyCspToHtml("<!doctype html><html><head></head></html>");
    expect(out).toBe(
      `<!doctype html>${buildCspMetaTag()}<html><head></head></html>`,
    );
  });

  it("keeps leading whitespace and mixed-case doctype before the meta", () => {
    const out = applyCspToHtml("  <!DOCTYPE html>\n<html></html>");
    expect(out.startsWith("  <!DOCTYPE html>")).toBe(true);
    expect(out.indexOf("<!DOCTYPE html>")).toBeLessThan(
      out.indexOf(buildCspMetaTag()),
    );
  });
});
