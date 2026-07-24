import { describe, expect, it } from "vitest";
import {
  buildCspMetaTag,
  buildCspString,
  escapeAttr,
  sanitizeDomain,
} from "./mcp-app-csp";

describe("sanitizeDomain", () => {
  it("passes through valid domains", () => {
    expect(sanitizeDomain("example.com")).toBe("example.com");
    expect(sanitizeDomain("*.example.com")).toBe("*.example.com");
    // CSP domains don't include protocol slashes - slashes are stripped
    expect(sanitizeDomain("example.com:8080")).toBe("example.com:8080");
  });

  it("strips injection characters", () => {
    // Semicolons, quotes, and spaces are stripped; * is allowed (CSP wildcard)
    expect(sanitizeDomain("' unsafe-eval; script-src *;")).toBe(
      "unsafe-evalscript-src*",
    );
    expect(sanitizeDomain('" onload=alert(1)')).toBe("onloadalert1");
    expect(sanitizeDomain("example.com; frame-ancestors *")).toBe(
      "example.comframe-ancestors*",
    );
  });

  it("strips whitespace", () => {
    expect(sanitizeDomain("example .com")).toBe("example.com");
  });
});

describe("buildCspString", () => {
  it("returns default CSP when no metadata provided", () => {
    const result = buildCspString();
    expect(result).toContain("default-src 'none'");
    expect(result).toContain("script-src 'self' 'unsafe-inline'");
    expect(result).toContain("style-src 'self' 'unsafe-inline'");
    expect(result).toContain("img-src 'self' data:");
    expect(result).toContain("media-src 'self' data:");
    expect(result).toContain("connect-src 'none'");
    expect(result).toContain("frame-src 'none'");
    expect(result).toContain("form-action 'none'");
    expect(result).toContain("base-uri 'none'");
  });

  it("returns default CSP for empty metadata", () => {
    const result = buildCspString({});
    expect(result).toContain("connect-src 'none'");
    expect(result).toContain("frame-src 'none'");
    expect(result).toContain("form-action 'none'");
  });

  it("always includes form-action 'none'", () => {
    const result = buildCspString({
      connectDomains: ["api.example.com"],
    });
    expect(result).toContain("form-action 'none'");
  });

  it("maps connectDomains to connect-src", () => {
    const result = buildCspString({
      connectDomains: ["api.example.com", "*.cdn.example.com"],
    });
    expect(result).toContain("connect-src api.example.com *.cdn.example.com");
  });

  it("maps resourceDomains to img/media/font/script/style-src", () => {
    const result = buildCspString({
      resourceDomains: ["cdn.example.com"],
    });
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

  it("does not include resourceDomains in script/style-src when not declared", () => {
    const result = buildCspString({});
    expect(result).toContain("script-src 'self' 'unsafe-inline'");
    expect(result).toContain("style-src 'self' 'unsafe-inline'");
    // Should NOT have trailing space after 'unsafe-inline'
    expect(result).not.toMatch(/script-src 'self' 'unsafe-inline' ;/);
  });

  it("maps frameDomains to frame-src", () => {
    const result = buildCspString({
      frameDomains: ["embed.example.com"],
    });
    expect(result).toContain("frame-src embed.example.com");
  });

  it("maps baseUriDomains to base-uri", () => {
    const result = buildCspString({
      baseUriDomains: ["example.com"],
    });
    expect(result).toContain("base-uri example.com");
  });

  it("sanitizes domains with injection attempts", () => {
    const result = buildCspString({
      connectDomains: ["example.com; script-src 'unsafe-eval'"],
    });
    // After sanitization, the semicolons, quotes, and spaces are stripped
    // so the domain can't inject new CSP directives
    expect(result).toContain("connect-src example.comscript-srcunsafe-eval");
    // The injected directive should not appear as a separate CSP directive
    expect(result).not.toMatch(/;\s*script-src\s+'unsafe-eval'/);
  });
});

describe("escapeAttr", () => {
  it("escapes double quotes", () => {
    expect(escapeAttr('hello "world"')).toBe("hello &quot;world&quot;");
  });

  it("escapes single quotes", () => {
    expect(escapeAttr("hello 'world'")).toBe("hello &#39;world&#39;");
  });

  it("escapes ampersands", () => {
    expect(escapeAttr("a & b")).toBe("a &amp; b");
  });

  it("escapes angle brackets", () => {
    expect(escapeAttr("<script>alert(1)</script>")).toBe(
      "&lt;script&gt;alert(1)&lt;/script&gt;",
    );
  });

  it("handles combination", () => {
    expect(escapeAttr(`"foo" & 'bar' <baz>`)).toBe(
      "&quot;foo&quot; &amp; &#39;bar&#39; &lt;baz&gt;",
    );
  });

  it("passes through safe strings", () => {
    expect(escapeAttr("default-src none")).toBe("default-src none");
  });
});

describe("buildCspMetaTag", () => {
  it("returns a valid meta tag", () => {
    const tag = buildCspMetaTag();
    expect(tag).toMatch(
      /^<meta http-equiv="Content-Security-Policy" content=".*">$/,
    );
    expect(tag).toContain("default-src");
  });

  it("escapes CSP content in the attribute", () => {
    const tag = buildCspMetaTag({
      connectDomains: ["example.com"],
    });
    expect(tag).toContain("connect-src example.com");
    // Verify it's inside a proper attribute
    expect(tag).toMatch(/content="[^"]+"/);
  });
});
