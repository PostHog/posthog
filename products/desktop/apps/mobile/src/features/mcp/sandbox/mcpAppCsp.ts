import type { McpUiResourceCsp } from "@modelcontextprotocol/ext-apps/app-bridge";

const DEFAULT_CSP =
  "default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; media-src 'self' data:; connect-src 'none'; object-src 'none'; frame-src 'none'; form-action 'none'; base-uri 'none'";

export function sanitizeDomain(domain: string): string {
  return domain.replace(/[^a-zA-Z0-9.*:-]/g, "");
}

export function buildCspString(csp?: McpUiResourceCsp): string {
  if (!csp) return DEFAULT_CSP;

  const resourceDomains = csp.resourceDomains?.length
    ? csp.resourceDomains.map(sanitizeDomain).join(" ")
    : "";
  const resourceSuffix = resourceDomains ? ` ${resourceDomains}` : "";

  const directives: string[] = [
    "default-src 'none'",
    `script-src 'self' 'unsafe-inline'${resourceSuffix}`,
    `style-src 'self' 'unsafe-inline'${resourceSuffix}`,
    "object-src 'none'",
    "form-action 'none'",
  ];

  if (csp.connectDomains?.length) {
    directives.push(
      `connect-src ${csp.connectDomains.map(sanitizeDomain).join(" ")}`,
    );
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

  if (csp.frameDomains?.length) {
    directives.push(
      `frame-src ${csp.frameDomains.map(sanitizeDomain).join(" ")}`,
    );
  } else {
    directives.push("frame-src 'none'");
  }

  if (csp.baseUriDomains?.length) {
    directives.push(
      `base-uri ${csp.baseUriDomains.map(sanitizeDomain).join(" ")}`,
    );
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
