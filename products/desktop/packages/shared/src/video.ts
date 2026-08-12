import { extensionOf } from "./image";

// Container formats Chromium (and Electron, which bundles proprietary codecs)
// can decode in a <video> element. Formats like avi, mkv, flv, wmv, and mpg are
// intentionally excluded — they generally fail to decode and would render a
// broken player rather than a clean preview.
export const VIDEO_MIME_TYPES: Record<string, string> = {
  mp4: "video/mp4",
  m4v: "video/mp4",
  mov: "video/quicktime",
  webm: "video/webm",
  ogv: "video/ogg",
};

const PLAYABLE_VIDEO_EXTENSIONS: ReadonlySet<string> = new Set(
  Object.keys(VIDEO_MIME_TYPES),
);

// Derived from VIDEO_MIME_TYPES so the playable set and the allow-list cannot
// drift apart when a new format is added.
export const ALLOWED_VIDEO_MIME_TYPES: ReadonlySet<string> = new Set(
  Object.values(VIDEO_MIME_TYPES),
);

// base64 inflates bytes by ~33%, so cap the inline preview to keep a large
// committed video from ballooning into a multi-hundred-MB data URL in the
// renderer. ~50MB of base64 is roughly a 37MB source file.
export const MAX_VIDEO_BASE64_LENGTH = 50 * 1024 * 1024;

export function isPlayableVideoFile(filename: string): boolean {
  const ext = extensionOf(filename);
  return ext.length > 0 && PLAYABLE_VIDEO_EXTENSIONS.has(ext);
}

export function getVideoMimeType(filePath: string): string {
  return VIDEO_MIME_TYPES[extensionOf(filePath)] ?? "application/octet-stream";
}

export function isAllowedVideoMimeType(mimeType: string): boolean {
  return ALLOWED_VIDEO_MIME_TYPES.has(mimeType.toLowerCase());
}

export function buildVideoDataUrl(mimeType: string, base64: string): string {
  return `data:${mimeType};base64,${base64}`;
}
