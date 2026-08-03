export const IMAGE_MIME_TYPES: Record<string, string> = {
  png: "image/png",
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  gif: "image/gif",
  webp: "image/webp",
  bmp: "image/bmp",
  ico: "image/x-icon",
  tiff: "image/tiff",
  tif: "image/tiff",
  svg: "image/svg+xml",
  heic: "image/heic",
  heif: "image/heif",
  avif: "image/avif",
};

const IMAGE_EXTENSIONS: ReadonlySet<string> = new Set(
  Object.keys(IMAGE_MIME_TYPES),
);

const RASTER_IMAGE_EXTENSIONS: ReadonlySet<string> = new Set([
  "png",
  "jpg",
  "jpeg",
  "gif",
  "webp",
  "bmp",
  "ico",
  "tiff",
  "tif",
  "avif",
]);

// SVG is intentionally excluded — SVG can contain <script> tags that execute
// when rendered as an <img> from a data URL. Heic/heif are excluded because
// Chromium cannot decode them in an <img> tag.
export const ALLOWED_IMAGE_MIME_TYPES: ReadonlySet<string> = new Set([
  "image/png",
  "image/jpeg",
  "image/gif",
  "image/webp",
  "image/bmp",
  "image/x-icon",
  "image/vnd.microsoft.icon",
  "image/tiff",
  "image/avif",
]);

export type ClaudeImageMimeType =
  | "image/jpeg"
  | "image/png"
  | "image/gif"
  | "image/webp";

const CLAUDE_IMAGE_MIME_TYPES: ReadonlySet<string> = new Set([
  "image/jpeg",
  "image/png",
  "image/gif",
  "image/webp",
]);

export const CLAUDE_IMAGE_EXTENSIONS: ReadonlySet<string> = new Set([
  "png",
  "jpg",
  "jpeg",
  "gif",
  "webp",
]);

export function isClaudeImageMimeType(
  mimeType: string,
): mimeType is ClaudeImageMimeType {
  return CLAUDE_IMAGE_MIME_TYPES.has(mimeType.toLowerCase());
}

const DATA_URL_PATTERN =
  /^data:([a-zA-Z]+\/[a-zA-Z0-9.+-]+)(?:;[a-zA-Z0-9-]+=[^;,]+)*;base64,([A-Za-z0-9+/=\s]+)$/;

const MAX_DATA_URL_LENGTH = 20 * 1024 * 1024;
export const MAX_IMAGE_BASE64_LENGTH = 15 * 1024 * 1024;

// Anthropic rejects a request whose per-image decoded size exceeds 5 MB with a
// 400. Guarding at this boundary keeps an oversized image from being embedded
// into the model payload (and, on resume, from re-triggering the same error on
// every subsequent turn).
export const MAX_CLAUDE_IMAGE_BYTES = 5 * 1024 * 1024;

/** Decoded byte size of a base64 string, without allocating the buffer. */
export function estimateBase64Bytes(base64: string): number {
  const padding = base64.endsWith("==") ? 2 : base64.endsWith("=") ? 1 : 0;
  return Math.floor((base64.length * 3) / 4) - padding;
}

export interface ParsedImageDataUrl {
  mimeType: string;
  base64: string;
}

export function extensionOf(filename: string): string {
  const slash = Math.max(filename.lastIndexOf("/"), filename.lastIndexOf("\\"));
  const basename = slash >= 0 ? filename.slice(slash + 1) : filename;
  const cleanBasename = basename.split(/[?#]/)[0];
  const dot = cleanBasename.lastIndexOf(".");
  return dot > 0 ? cleanBasename.slice(dot + 1).toLowerCase() : "";
}

export function isImageFile(filename: string): boolean {
  const ext = extensionOf(filename);
  return ext.length > 0 && IMAGE_EXTENSIONS.has(ext);
}

export function isRasterImageFile(filename: string): boolean {
  const ext = extensionOf(filename);
  return ext.length > 0 && RASTER_IMAGE_EXTENSIONS.has(ext);
}

export function isClaudeImageFile(filename: string): boolean {
  const ext = extensionOf(filename);
  return ext.length > 0 && CLAUDE_IMAGE_EXTENSIONS.has(ext);
}

export function isGifFile(filename: string): boolean {
  return extensionOf(filename) === "gif";
}

export function getImageMimeType(filePath: string): string {
  return IMAGE_MIME_TYPES[extensionOf(filePath)] ?? "application/octet-stream";
}

export function isAllowedImageMimeType(mimeType: string): boolean {
  return ALLOWED_IMAGE_MIME_TYPES.has(mimeType.toLowerCase());
}

export function parseImageDataUrl(value: string): ParsedImageDataUrl | null {
  if (typeof value !== "string" || value.length === 0) return null;
  if (value.length > MAX_DATA_URL_LENGTH) return null;
  if (!/^\s{0,1024}data:/.test(value)) return null;

  const trimmed = value.trim();
  if (trimmed.length === 0) return null;

  const match = DATA_URL_PATTERN.exec(trimmed);
  if (!match) return null;

  const mimeType = match[1].toLowerCase();
  if (!ALLOWED_IMAGE_MIME_TYPES.has(mimeType)) return null;

  const base64 = match[2].replace(/\s+/g, "");
  if (base64.length === 0 || base64.length > MAX_IMAGE_BASE64_LENGTH) {
    return null;
  }

  return { mimeType, base64 };
}

export function buildImageDataUrl(mimeType: string, base64: string): string {
  return `data:${mimeType};base64,${base64}`;
}
