import { getImageMimeType, isAllowedImageMimeType } from "@posthog/shared";
import { applyCspToHtml } from "../../mcp-apps/utils/mcp-app-csp";
import { injectArtifactHtmlCommentBridge } from "./artifactHtmlCommentBridge";

function removeAutomaticRedirects(html: string): string {
  const document = new DOMParser().parseFromString(html, "text/html");
  const refreshElements = Array.from(
    document.querySelectorAll<HTMLMetaElement>("meta[http-equiv]"),
  ).filter((element) => element.httpEquiv.trim().toLowerCase() === "refresh");
  if (refreshElements.length === 0) return html;

  for (const element of refreshElements) element.remove();
  const doctype = html.match(/^\s*<!doctype[^>]*>/i)?.[0] ?? "";
  return doctype + document.documentElement.outerHTML;
}

export function artifactHtmlDocument(
  html: string,
  commentBridgeChannel?: string,
): string {
  // HTML artifacts are document previews, not apps. Canvases are the supported
  // surface for authored JavaScript; only this trusted annotation bridge runs here.
  const safeHtml = removeAutomaticRedirects(html);
  if (!commentBridgeChannel) {
    return applyCspToHtml(safeHtml, undefined, null);
  }
  const nonce = crypto.randomUUID();
  return applyCspToHtml(
    injectArtifactHtmlCommentBridge(safeHtml, commentBridgeChannel, nonce),
    undefined,
    nonce,
  );
}
export async function artifactPreviewBlob(
  blob: Blob,
  filename: string,
): Promise<Blob> {
  const filenameMimeType = getImageMimeType(filename);
  const imageMimeType = isAllowedImageMimeType(blob.type)
    ? blob.type.toLowerCase()
    : filenameMimeType;

  if (isAllowedImageMimeType(imageMimeType)) {
    return new Blob([blob], { type: imageMimeType });
  }
  // SVG is kept out of the shared <img> allowlist because its scripts can run
  // when it comes from a data URL, but the artifact preview renders it from a
  // blob in an <img>, which never runs scripts. Type it so that surface picks
  // it up instead of the browser offering a download.
  if (filenameMimeType === "image/svg+xml") {
    return new Blob([blob], { type: "image/svg+xml" });
  }
  return blob;
}
