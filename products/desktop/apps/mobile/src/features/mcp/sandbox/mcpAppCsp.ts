import type { McpUiResourceCsp } from "@modelcontextprotocol/ext-apps/app-bridge";

const DEFAULT_CSP =
  "default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; media-src 'self' data:; connect-src 'none'; object-src 'none'; frame-src 'none'; form-action 'none'; base-uri 'none'";

// The `ui.csp` fields are named `*Domains`, but what a server puts in them is a
// CSP source expression: an origin carrying a scheme, like
// `https://cdn.jsdelivr.net` or `wss://api.example.com`, optionally with a
// wildcard subdomain, a port, or a path.
const CSP_SOURCE =
  /^(?:[a-zA-Z][a-zA-Z0-9+.-]*:\/\/)?(?:\*|(?:\*\.)?[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)*)(?::(?:\d+|\*))?(?:\/[^\s"';,]*)?$/;

// A declaration that is not a source expression is dropped whole, rather than
// having its offending characters removed so that it fits. Editing it down can
// produce a valid origin the server never declared (`example .com` becomes
// `example.com`), and the spec lets a host restrict what was declared but not
// widen it. Dropping keeps that decision visible instead of guessing at intent.
function cspSources(declared: string[] | undefined): string[] {
  return declared?.filter((source) => CSP_SOURCE.test(source)) ?? [];
}

export function buildCspString(csp?: McpUiResourceCsp): string {
  if (!csp) return DEFAULT_CSP;

  const resourceDomains = cspSources(csp.resourceDomains).join(" ");
  const resourceSuffix = resourceDomains ? ` ${resourceDomains}` : "";
  const connectDomains = cspSources(csp.connectDomains).join(" ");
  const frameDomains = cspSources(csp.frameDomains).join(" ");
  const baseUriDomains = cspSources(csp.baseUriDomains).join(" ");

  const directives: string[] = [
    "default-src 'none'",
    `script-src 'self' 'unsafe-inline'${resourceSuffix}`,
    `style-src 'self' 'unsafe-inline'${resourceSuffix}`,
    "object-src 'none'",
    "form-action 'none'",
  ];

  if (connectDomains) {
    directives.push(`connect-src ${connectDomains}`);
  } else {
    directives.push("connect-src 'none'");
  }

  if (resourceDomains) {
    directives.push(`img-src 'self' data: ${resourceDomains}`);
    directives.push(`media-src 'self' data: ${resourceDomains}`);
    directives.push(`font-src ${resourceDomains}`);
  } else {
    directives.push("img-src 'self' data:");
    directives.push("media-src 'self' data:");
  }

  if (frameDomains) {
    directives.push(`frame-src ${frameDomains}`);
  } else {
    directives.push("frame-src 'none'");
  }

  if (baseUriDomains) {
    directives.push(`base-uri ${baseUriDomains}`);
  } else {
    directives.push("base-uri 'none'");
  }

  return directives.join("; ");
}

export function escapeAttr(str: string): string {
  return str
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

export function buildCspMetaTag(csp?: McpUiResourceCsp): string {
  return `<meta http-equiv="Content-Security-Policy" content="${escapeAttr(buildCspString(csp))}">`;
}

export function applyCspToHtml(html: string, csp?: McpUiResourceCsp): string {
  const meta = buildCspMetaTag(csp);
  // The doctype must stay first, or the frame drops into quirks mode.
  const doctype = html.match(/^\s*<!doctype[^>]*>/i);
  if (doctype) {
    return (
      html.slice(0, doctype[0].length) + meta + html.slice(doctype[0].length)
    );
  }
  return meta + html;
}
