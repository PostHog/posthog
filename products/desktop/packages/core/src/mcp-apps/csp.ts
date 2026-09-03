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

// The `ui.csp` fields are named `*Domains`, but what a server puts in them is a
// CSP source expression: an origin carrying a scheme, like
// `https://cdn.jsdelivr.net` or `wss://api.example.com`, optionally with a
// wildcard subdomain, a port, or a path. The `\.?` after the host labels is the
// root dot of a fully qualified name, which the grammar permits. The path stops
// at `;` and `,` because the grammar excludes both, and they are what a source
// would need to escape its directive.
//
// @see https://www.w3.org/TR/CSP3/#grammardef-host-source
const CSP_SOURCE =
  /^(?:[a-zA-Z][a-zA-Z0-9+.-]*:\/\/)?(?:\*|(?:\*\.)?[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)*\.?)(?::(?:\d+|\*))?(?:\/[^\s"';,]*)?$/;

// A declaration that is not a source expression is dropped whole, rather than
// having its offending characters removed so that it fits. Editing it down can
// produce a valid origin the server never declared (`example .com` becomes
// `example.com`), and the spec lets a host restrict what was declared but not
// widen it. Dropping keeps that decision visible instead of guessing at intent.
function cspSources(declared: string[] | undefined): string[] {
  return declared?.filter((source) => CSP_SOURCE.test(source)) ?? [];
}

export function buildCspString(
  csp?: McpUiResourceCsp,
  scriptNonce?: string | null,
): string {
  if (!csp && scriptNonce === undefined) return DEFAULT_CSP;

  const resourceSources = cspSources(csp?.resourceDomains);
  const connectSources = cspSources(csp?.connectDomains);
  const frameSources = cspSources(csp?.frameDomains);
  const baseUriSources = cspSources(csp?.baseUriDomains);

  const resourceDomainsSuffix = resourceSources.length
    ? ` ${resourceSources.join(" ")}`
    : "";

  const directives: string[] = [
    "default-src 'none'",
    scriptNonce === undefined
      ? `script-src 'self' 'unsafe-inline'${resourceDomainsSuffix}`
      : scriptNonce === null
        ? "script-src 'none'"
        : `script-src 'nonce-${scriptNonce}'`,
    `style-src 'self' 'unsafe-inline'${resourceDomainsSuffix}`,
    "object-src 'none'",
    "form-action 'none'",
  ];

  if (connectSources.length) {
    directives.push(`connect-src ${connectSources.join(" ")}`);
  } else {
    directives.push("connect-src 'none'");
  }

  if (resourceSources.length) {
    const domains = resourceSources.join(" ");
    directives.push(`img-src 'self' data: ${domains}`);
    directives.push(`media-src 'self' data: ${domains}`);
    directives.push(`font-src ${domains}`);
  } else {
    directives.push("img-src 'self' data:");
    directives.push("media-src 'self' data:");
  }

  if (frameSources.length) {
    directives.push(`frame-src ${frameSources.join(" ")}`);
  } else {
    directives.push("frame-src 'none'");
  }

  if (baseUriSources.length) {
    directives.push(`base-uri ${baseUriSources.join(" ")}`);
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

export function buildCspMetaTag(
  csp?: McpUiResourceCsp,
  scriptNonce?: string | null,
): string {
  const cspString = buildCspString(csp, scriptNonce);
  return `<meta http-equiv="Content-Security-Policy" content="${escapeAttr(cspString)}">`;
}

// After any doctype, which must stay first or the frame enters quirks mode.
export function applyCspToHtml(
  html: string,
  csp?: McpUiResourceCsp,
  scriptNonce?: string | null,
): string {
  const meta = buildCspMetaTag(csp, scriptNonce);
  const doctype = html.match(/^\s*<!doctype[^>]*>/i);
  if (doctype) {
    return (
      html.slice(0, doctype[0].length) + meta + html.slice(doctype[0].length)
    );
  }
  return meta + html;
}
