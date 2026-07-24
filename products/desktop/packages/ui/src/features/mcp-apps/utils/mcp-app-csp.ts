/**
 * Builds Content Security Policy directives for MCP App iframes.
 *
 * MCP Apps run inside a sandboxed iframe with a null origin. The CSP restricts
 * what the app can load (scripts, styles, images, connections, etc.) based on
 * domains declared in the resource's `ui.csp` metadata. When no CSP metadata
 * is provided, a restrictive default is used.
 *
 * @see https://modelcontextprotocol.io/specification/2025-03-26/extensions/mcp-apps
 */

import type { McpUiResourceCsp } from "@modelcontextprotocol/ext-apps/app-bridge";

// Per MCP Apps spec, the default CSP includes 'self' in script/style/img/media-src.
// 'self' is effectively inert in our sandbox model because the inner iframe runs
// without allow-same-origin (null origin), but we include it for spec compliance.
const DEFAULT_CSP =
  "default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; media-src 'self' data:; connect-src 'none'; object-src 'none'; frame-src 'none'; form-action 'none'; base-uri 'none'";

export function sanitizeDomain(domain: string): string {
  return domain.replace(/[^a-zA-Z0-9.*:-]/g, "");
}

export function buildCspString(csp?: McpUiResourceCsp): string {
  if (!csp) return DEFAULT_CSP;

  const resourceDomainsSuffix = csp.resourceDomains?.length
    ? ` ${csp.resourceDomains.map(sanitizeDomain).join(" ")}`
    : "";

  const directives: string[] = [
    "default-src 'none'",
    `script-src 'self' 'unsafe-inline'${resourceDomainsSuffix}`,
    `style-src 'self' 'unsafe-inline'${resourceDomainsSuffix}`,
    "object-src 'none'",
    "form-action 'none'",
  ];

  if (csp.connectDomains?.length) {
    const domains = csp.connectDomains.map(sanitizeDomain).join(" ");
    directives.push(`connect-src ${domains}`);
  } else {
    directives.push("connect-src 'none'");
  }

  if (csp.resourceDomains?.length) {
    const domains = csp.resourceDomains.map(sanitizeDomain).join(" ");
    directives.push(`img-src 'self' data: ${domains}`);
    directives.push(`media-src 'self' data: ${domains}`);
    directives.push(`font-src ${domains}`);
  } else {
    directives.push("img-src 'self' data:");
    directives.push("media-src 'self' data:");
  }

  if (csp.frameDomains?.length) {
    const domains = csp.frameDomains.map(sanitizeDomain).join(" ");
    directives.push(`frame-src ${domains}`);
  } else {
    directives.push("frame-src 'none'");
  }

  if (csp.baseUriDomains?.length) {
    const domains = csp.baseUriDomains.map(sanitizeDomain).join(" ");
    directives.push(`base-uri ${domains}`);
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
  const cspString = buildCspString(csp);
  return `<meta http-equiv="Content-Security-Policy" content="${escapeAttr(cspString)}">`;
}
