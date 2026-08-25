import {
  estimateBase64Bytes,
  isClaudeImageMimeType,
  MAX_CLAUDE_IMAGE_BYTES,
} from "@posthog/shared";

function unprocessableImageReason(value: unknown): string | null {
  if (!value || typeof value !== "object") return null;
  const block = value as {
    type?: unknown;
    data?: unknown;
    mimeType?: unknown;
    source?: { data?: unknown; media_type?: unknown };
  };
  if (block.type !== "image") return null;

  const data =
    typeof block.data === "string"
      ? block.data
      : typeof block.source?.data === "string"
        ? block.source.data
        : null;
  const mimeType =
    typeof block.mimeType === "string"
      ? block.mimeType
      : typeof block.source?.media_type === "string"
        ? block.source.media_type
        : null;
  if (data == null) return null;
  if (data.trim().length === 0) return "image data is empty";
  if (mimeType != null && !isClaudeImageMimeType(mimeType)) {
    return `unsupported image type ${mimeType}`;
  }
  if (estimateBase64Bytes(data) > MAX_CLAUDE_IMAGE_BYTES) {
    return "image exceeds the 5 MB per-image limit";
  }
  return null;
}

export function neutralizeUnprocessableImages(value: unknown): {
  changed: boolean;
  value: unknown;
} {
  const reason = unprocessableImageReason(value);
  if (reason) {
    return {
      changed: true,
      value: {
        type: "text",
        text: `[Removed unprocessable image: ${reason}]`,
      },
    };
  }
  if (Array.isArray(value)) {
    let changed = false;
    const items = value.map((item) => {
      const result = neutralizeUnprocessableImages(item);
      changed ||= result.changed;
      return result.value;
    });
    return { changed, value: changed ? items : value };
  }
  if (!value || typeof value !== "object") {
    return { changed: false, value };
  }

  const record = value as Record<string, unknown>;
  if (!("content" in record)) {
    return { changed: false, value };
  }
  const result = neutralizeUnprocessableImages(record.content);
  return result.changed
    ? { changed: true, value: { ...record, content: result.value } }
    : { changed: false, value };
}
