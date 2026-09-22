import { applyCspToHtml } from "@posthog/core/mcp-apps/csp";
import { getImageMimeType, isAllowedImageMimeType } from "@posthog/shared";
import { injectArtifactHtmlCommentBridge } from "./artifactHtmlCommentBridge";
import type { CommentSurfaceTheme } from "./selectionCommentAction";

function removeAutomaticRedirects(html: string): string {
  if (!/<meta\b/i.test(html) || !/http-equiv\s*=/i.test(html)) return html;
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
  commentSurfaceTheme: CommentSurfaceTheme = "light",
): string {
  // HTML artifacts are document previews, not apps. Canvases are the supported
  // surface for authored JavaScript; only this trusted annotation bridge runs here.
  const safeHtml = removeAutomaticRedirects(html);
  if (!commentBridgeChannel) {
    return applyCspToHtml(safeHtml, undefined, null);
  }
  const nonce = crypto.randomUUID();
  return applyCspToHtml(
    injectArtifactHtmlCommentBridge(safeHtml, {
      channel: commentBridgeChannel,
      theme: commentSurfaceTheme,
      nonce,
    }),
    undefined,
    nonce,
  );
}

export function scriptedArtifactHtmlDocument(
  html: string,
  commentBridgeChannel?: string,
  commentSurfaceTheme: CommentSurfaceTheme = "light",
): string {
  const safeHtml = removeAutomaticRedirects(html);
  if (!commentBridgeChannel) return applyCspToHtml(safeHtml);
  return applyCspToHtml(
    injectArtifactHtmlCommentBridge(safeHtml, {
      channel: commentBridgeChannel,
      theme: commentSurfaceTheme,
    }),
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
