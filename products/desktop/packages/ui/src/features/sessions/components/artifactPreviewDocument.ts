import { getImageMimeType, isAllowedImageMimeType } from "@posthog/shared";
import { applyCspToHtml } from "../../mcp-apps/utils/mcp-app-csp";

function extension(filename: string): string {
  return filename.split(".").pop()?.toLowerCase() ?? "";
}

export function artifactHtmlDocument(html: string): string {
  return applyCspToHtml(html);
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
  if (["html", "htm"].includes(extension(filename))) {
    return new Blob([artifactHtmlDocument(await blob.text())], {
      type: "text/html",
    });
  }
  return blob;
}
