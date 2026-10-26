import { extensionOf, IMAGE_MIME_TYPES } from "./image";

export const AUDIO_VIDEO_EXTENSIONS: ReadonlySet<string> = new Set([
  "mp3",
  "mp4",
  "wav",
  "avi",
  "mov",
  "mkv",
  "webm",
  "mpg",
  "mpeg",
  "flac",
  "ogg",
  "ogv",
  "m4a",
  "m4v",
  "aac",
]);

export const ARCHIVE_EXTENSIONS: ReadonlySet<string> = new Set([
  "zip",
  "tar",
  "gz",
  "tgz",
  "bz2",
  "xz",
  "rar",
  "7z",
]);

export const EXECUTABLE_EXTENSIONS: ReadonlySet<string> = new Set([
  "exe",
  "dll",
  "so",
  "dylib",
  "wasm",
  "bin",
  "o",
]);

export const FONT_EXTENSIONS: ReadonlySet<string> = new Set([
  "ttf",
  "otf",
  "woff",
  "woff2",
  "eot",
]);

export const DOCUMENT_BINARY_EXTENSIONS: ReadonlySet<string> = new Set(["pdf"]);

// SVG is excluded — it is XML text and consumers like title generation read
// it as text rather than treating it as opaque bytes.
export const BINARY_EXTENSIONS: ReadonlySet<string> = new Set([
  ...Object.keys(IMAGE_MIME_TYPES).filter((ext) => ext !== "svg"),
  ...AUDIO_VIDEO_EXTENSIONS,
  ...ARCHIVE_EXTENSIONS,
  ...EXECUTABLE_EXTENSIONS,
  ...FONT_EXTENSIONS,
  ...DOCUMENT_BINARY_EXTENSIONS,
]);

export function isBinaryFile(filename: string): boolean {
  const ext = extensionOf(filename);
  return ext.length > 0 && BINARY_EXTENSIONS.has(ext);
}
