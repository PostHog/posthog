import { describe, expect, it } from "vitest";
import {
  buildSandboxDocument,
  decodeJsxUnicodeEscapes,
  resolveExternalAnchorUrl,
} from "./sandboxRuntime";

describe("decodeJsxUnicodeEscapes", () => {
  it.each([
    {
      name: "decodes 4-hex escapes",
      input: "Survey started Jun 20, 2026 \\u00b7 live \\u00b7 data",
      expected: "Survey started Jun 20, 2026 · live · data",
    },
    { name: "decodes braced code points", input: "\\u{1F600}", expected: "😀" },
    {
      name: "decodes surrogate pairs",
      input: "\\ud83d\\ude00",
      expected: "😀",
    },
    {
      name: "decodes braced escapes shorter than 4 digits",
      input: "\\u{b7}",
      expected: "·",
    },
    {
      name: "leaves out-of-range code points intact",
      input: "\\u{110000}",
      expected: "\\u{110000}",
    },
    {
      name: "leaves incomplete escapes intact",
      input: "\\u00 and \\uZZZZ",
      expected: "\\u00 and \\uZZZZ",
    },
    {
      name: "leaves already-decoded text untouched",
      input: "plain · text",
      expected: "plain · text",
    },
    {
      name: "decodes valid escapes next to invalid ones",
      input: "\\u00b7 then \\u{110000}",
      expected: "· then \\u{110000}",
    },
  ])("$name", ({ input, expected }) => {
    expect(decodeJsxUnicodeEscapes(input)).toBe(expected);
  });
});

describe("buildSandboxDocument", () => {
  it("inlines the unicode-escape decoder into the bootstrap", () => {
    const html = buildSandboxDocument("edit");
    expect(html).toContain(
      "const decodeUnicodeEscapes = function decodeJsxUnicodeEscapes(",
    );
    expect(html).toContain("jsxUnicodeEscapesPlugin");
  });

  it("inlines the external-anchor resolver into the bootstrap", () => {
    const html = buildSandboxDocument("edit");
    expect(html).toContain(
      "const resolveExternalAnchorUrl = function resolveExternalAnchorUrl(",
    );
    expect(html).toContain('"open-external"');
    expect(html).toContain("event.defaultPrevented");
  });

  // The document paints before its stylesheets load and before the host's
  // theme message arrives. A light fallback there flashed white over a dark
  // app every time a canvas preview scrolled into view.
  it("paints nothing of its own before the host theme lands", () => {
    const html = buildSandboxDocument("edit");
    expect(html).toContain("background: var(--background, transparent)");
    expect(html).not.toContain("var(--background, #fff)");
    expect(html).toContain("html.dark { color-scheme: dark; }");
  });
});

describe("content security policy", () => {
  // Pull the CSP out of the <meta http-equiv> tag and index it by directive.
  const cspDirectives = (html: string): Map<string, string[]> => {
    const match = html.match(
      /<meta http-equiv="Content-Security-Policy" content="([^"]*)"/,
    );
    if (!match) throw new Error("no CSP meta tag in document");
    const directives = new Map<string, string[]>();
    for (const part of match[1].split(";")) {
      const [name, ...values] = part.trim().split(/\s+/).filter(Boolean);
      if (name) directives.set(name, values);
    }
    return directives;
  };

  it.each([
    { name: "without analytics host", analyticsApiHost: undefined },
    { name: "with analytics host", analyticsApiHost: "https://us.posthog.com" },
  ])(
    "does not expose a bare https: wildcard on img-src in edit mode ($name)",
    ({ analyticsApiHost }) => {
      const directives = cspDirectives(
        buildSandboxDocument("edit", analyticsApiHost),
      );
      const imgSrc = directives.get("img-src") ?? [];
      // A bare `https:` token allows every https origin, which is the exfiltration
      // channel, because img loads are not governed by connect-src. Scheme-scoped host
      // entries like `https://esm.sh` are fine; the standalone `https:` is not.
      expect(imgSrc).not.toContain("https:");
    },
  );

  it.each([
    { name: "without analytics host", analyticsApiHost: undefined },
    { name: "with analytics host", analyticsApiHost: "https://us.posthog.com" },
  ])(
    "keeps img-src host egress mirrored to connect-src in edit mode ($name)",
    ({ analyticsApiHost }) => {
      const directives = cspDirectives(
        buildSandboxDocument("edit", analyticsApiHost),
      );
      const imgSrc = directives.get("img-src") ?? [];
      const connectSrc = directives.get("connect-src") ?? [];
      // Inline images may use data:/blob:; every remote host img-src permits must
      // also be a connect-src host, so image egress can't exceed connect egress.
      expect(imgSrc).toEqual(expect.arrayContaining(["data:", "blob:"]));
      const imgHosts = imgSrc.filter((v) => v !== "data:" && v !== "blob:");
      expect(imgHosts).toEqual(connectSrc);
    },
  );

  it("locks img-src to self plus data:/blob: in view mode", () => {
    const directives = cspDirectives(buildSandboxDocument("view"));
    expect(directives.get("img-src")).toEqual(["data:", "blob:", "'self'"]);
    expect(directives.get("img-src")).not.toContain("https:");
  });
});

describe("resolveExternalAnchorUrl", () => {
  const clickTarget = (html: string, selector: string): Element => {
    const container = document.createElement("div");
    container.innerHTML = html;
    const el = container.querySelector(selector);
    if (!el) throw new Error(`selector ${selector} not found`);
    return el;
  };

  it("resolves a click inside a target=_blank anchor to its absolute URL", () => {
    const target = clickTarget(
      '<a href="https://posthog.com/docs" target="_blank"><span>docs</span></a>',
      "span",
    );
    expect(resolveExternalAnchorUrl(target)).toBe("https://posthog.com/docs");
  });

  it("matches the _blank keyword case-insensitively", () => {
    const target = clickTarget(
      '<a href="https://posthog.com" target="_Blank">x</a>',
      "a",
    );
    expect(resolveExternalAnchorUrl(target)).toBe("https://posthog.com/");
  });

  it("resolves SVG anchors via the href attribute", () => {
    const target = clickTarget(
      '<svg><a href="https://posthog.com" target="_blank"><text>x</text></a></svg>',
      "text",
    );
    expect(resolveExternalAnchorUrl(target)).toBe("https://posthog.com/");
  });

  it.each([
    {
      name: "anchors without target=_blank",
      html: '<a href="https://posthog.com">x</a>',
      selector: "a",
    },
    {
      name: "relative hrefs (would resolve against the host base URL)",
      html: '<a href="/settings" target="_blank">x</a>',
      selector: "a",
    },
    {
      name: "empty hrefs",
      html: '<a href="" target="_blank">x</a>',
      selector: "a",
    },
    {
      name: "clicks outside any anchor",
      html: "<button>x</button>",
      selector: "button",
    },
  ])("returns null for $name", ({ html, selector }) => {
    expect(resolveExternalAnchorUrl(clickTarget(html, selector))).toBeNull();
  });

  it("returns null for non-Element targets", () => {
    expect(resolveExternalAnchorUrl(null)).toBeNull();
    expect(resolveExternalAnchorUrl(document.createTextNode("x"))).toBeNull();
  });
});
