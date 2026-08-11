import type { TaskArtifactUploadRequest } from "@posthog/api-client/posthog-client";
import type { PendingAttachment } from "../composer/attachments/types";

/**
 * The type the task API records for files a person uploaded, as opposed to
 * agent output. Confirmed against `TASK_RUN_ARTIFACT_TYPE_CHOICES` and
 * `get_task_run_artifact_max_size_bytes`, which only applies the smaller PDF
 * ceiling to this type.
 */
export const USER_UPLOAD_ARTIFACT_TYPE = "user_attachment";

/** Free-form origin marker, matching the `posthog_mobile` label used elsewhere. */
export const USER_UPLOAD_ARTIFACT_SOURCE = "posthog_mobile";

const DEFAULT_CONTENT_TYPE = "application/octet-stream";

/** Mirrors the server's per-type ceilings in `products/tasks/backend`. */
export const MAX_UPLOAD_BYTES = 30 * 1024 * 1024;
export const MAX_PDF_UPLOAD_BYTES = 10 * 1024 * 1024;

const CONTENT_TYPE_BY_EXTENSION: Record<string, string> = {
  bmp: "image/bmp",
  csv: "text/csv",
  gif: "image/gif",
  heic: "image/heic",
  html: "text/html",
  jpeg: "image/jpeg",
  jpg: "image/jpeg",
  json: "application/json",
  log: "text/plain",
  md: "text/markdown",
  pdf: "application/pdf",
  png: "image/png",
  svg: "image/svg+xml",
  toml: "application/toml",
  tsv: "text/tab-separated-values",
  txt: "text/plain",
  webp: "image/webp",
  xml: "application/xml",
  yaml: "application/yaml",
  yml: "application/yaml",
  zip: "application/zip",
};

function extension(fileName: string): string {
  const dot = fileName.lastIndexOf(".");
  return dot === -1 ? "" : fileName.slice(dot + 1).toLowerCase();
}

/**
 * Pickers hand back a MIME type that is sometimes missing and sometimes the
 * useless `application/octet-stream`; fall back to the extension in both cases
 * so the stored artifact previews correctly later.
 */
export function deriveUploadContentType(
  fileName: string,
  pickerMimeType?: string | null,
): string {
  const picked = pickerMimeType?.split(";")[0]?.trim().toLowerCase() ?? "";
  if (picked && picked !== DEFAULT_CONTENT_TYPE) return picked;
  return CONTENT_TYPE_BY_EXTENSION[extension(fileName)] ?? DEFAULT_CONTENT_TYPE;
}

export function maxUploadBytes(fileName: string, contentType: string): number {
  if (extension(fileName) === "pdf" || contentType === "application/pdf") {
    return MAX_PDF_UPLOAD_BYTES;
  }
  return MAX_UPLOAD_BYTES;
}

/**
 * Rejects a file the server would reject anyway, so the user sees the reason
 * before waiting through a prepare round-trip. `null` means "good to upload".
 */
export function uploadSizeError(
  fileName: string,
  contentType: string,
  sizeBytes: number,
): string | null {
  if (sizeBytes <= 0) return `${fileName} is empty.`;
  const limit = maxUploadBytes(fileName, contentType);
  if (sizeBytes > limit) {
    return `${fileName} exceeds the ${Math.floor(limit / (1024 * 1024))}MB upload limit.`;
  }
  return null;
}

export function buildArtifactUploadRequest(
  attachment: Pick<PendingAttachment, "fileName" | "mimeType">,
  sizeBytes: number,
): TaskArtifactUploadRequest {
  return {
    name: attachment.fileName,
    type: USER_UPLOAD_ARTIFACT_TYPE,
    source: USER_UPLOAD_ARTIFACT_SOURCE,
    size: sizeBytes,
    content_type: deriveUploadContentType(
      attachment.fileName,
      attachment.mimeType,
    ),
  };
}
