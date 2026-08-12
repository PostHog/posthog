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
import { CSP_VIOLATION_NOTIFICATION } from "../../../shell/cspViolationCollector";

// Per MCP Apps spec, the default CSP includes 'self' in script/style/img/media-src.
// 'self' is effectively inert in our sandbox model because the inner iframe runs
// without allow-same-origin (null origin), but we include it for spec compliance.
const DEFAULT_CSP =
  "default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; media-src 'self' data:; connect-src 'none'; object-src 'none'; frame-src 'none'; form-action 'none'; base-uri 'none'";

export function sanitizeDomain(domain: string): string {
  return domain.replace(/[^a-zA-Z0-9.*:-]/g, "");
}

export function buildCspString(
  csp?: McpUiResourceCsp,
  scriptNonce?: string | null,
): string {
  if (!csp && scriptNonce === undefined) return DEFAULT_CSP;

  const resourceDomainsSuffix = csp?.resourceDomains?.length
    ? ` ${csp.resourceDomains.map(sanitizeDomain).join(" ")}`
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

  if (csp?.connectDomains?.length) {
    const domains = csp.connectDomains.map(sanitizeDomain).join(" ");
    directives.push(`connect-src ${domains}`);
  } else {
    directives.push("connect-src 'none'");
  }

  if (csp?.resourceDomains?.length) {
    const domains = csp.resourceDomains.map(sanitizeDomain).join(" ");
    directives.push(`img-src 'self' data: ${domains}`);
    directives.push(`media-src 'self' data: ${domains}`);
    directives.push(`font-src ${domains}`);
  } else {
    directives.push("img-src 'self' data:");
    directives.push("media-src 'self' data:");
  }

  if (csp?.frameDomains?.length) {
    const domains = csp.frameDomains.map(sanitizeDomain).join(" ");
    directives.push(`frame-src ${domains}`);
  } else {
    directives.push("frame-src 'none'");
  }

  if (csp?.baseUriDomains?.length) {
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

export function buildCspMetaTag(
  csp?: McpUiResourceCsp,
  scriptNonce?: string | null,
): string {
  const cspString = buildCspString(csp, scriptNonce);
  return `<meta http-equiv="Content-Security-Policy" content="${escapeAttr(cspString)}">`;
}

/**
 * Inline script that ships the frame's own CSP violations back out to the host.
 *
 * A policy delivered in a `<meta>` element cannot report: `report-uri` and
 * `report-to` are ignored there, and `report-to` would need a
 * `Reporting-Endpoints` response header the frame never gets. The frame also
 * has an opaque origin, so the sandbox proxy cannot read its reports from the
 * outside either. That leaves collecting them in-document and posting them to
 * the parent, which relays to the host.
 *
 * Serving the frame over the `mcp-sandbox:` protocol to get real headers on it
 * does not help, and is worth not retrying: on Electron 42 a header-delivered
 * policy is enforced but never reported. In a document served that way, with
 * both `report-uri` and `report-to` naming an https endpoint, a violation the
 * page's own `ReportingObserver` saw produced no request, while a `sendBeacon`
 * to the same endpoint went out — so the reporting pipeline is what is absent,
 * not the network.
 *
 * The payload is the Reporting API's own JSON, so the host can forward it to
 * PostHog's `/report/` endpoint unchanged, exactly as a browser would.
 */
export function buildCspViolationReporterScript(
  scriptNonce?: string | null,
): string {
  // script-src 'none' — no script runs in the frame, including this one.
  if (scriptNonce === null) return "";

  const nonceAttr = scriptNonce ? ` nonce="${escapeAttr(scriptNonce)}"` : "";
  // `buffered: true` also delivers violations from before this script ran.
  return `<script${nonceAttr}>(function(){var send=function(report){try{window.parent.postMessage({jsonrpc:"2.0",method:"${CSP_VIOLATION_NOTIFICATION}",params:{report:report}},"*")}catch(err){}};try{if(typeof ReportingObserver==="function"){new ReportingObserver(function(reports){for(var i=0;i<reports.length;i++){send(reports[i].toJSON())}},{types:["csp-violation"],buffered:true}).observe();return}}catch(err){}document.addEventListener("securitypolicyviolation",function(event){send({type:"csp-violation",url:event.documentURI,body:{documentURL:event.documentURI,referrer:event.referrer,blockedURL:event.blockedURI,effectiveDirective:event.effectiveDirective,originalPolicy:event.originalPolicy,disposition:event.disposition,sourceFile:event.sourceFile,lineNumber:event.lineNumber,columnNumber:event.columnNumber,statusCode:event.statusCode,sample:event.sample}})})})()</script>`;
}

// After any doctype, which must stay first or the frame enters quirks mode.
export function applyCspToHtml(
  html: string,
  csp?: McpUiResourceCsp,
  scriptNonce?: string | null,
): string {
  const preamble =
    buildCspMetaTag(csp, scriptNonce) +
    buildCspViolationReporterScript(scriptNonce);
  const doctype = html.match(/^\s*<!doctype[^>]*>/i);
  if (doctype) {
    return (
      html.slice(0, doctype[0].length) +
      preamble +
      html.slice(doctype[0].length)
    );
  }
  return preamble + html;
}
