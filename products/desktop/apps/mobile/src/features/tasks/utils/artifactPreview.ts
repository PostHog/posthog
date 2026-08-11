import { isRasterImageFile } from "@posthog/shared";

export type ArtifactPreviewKind =
  | "image"
  | "markdown"
  | "html"
  | "json"
  | "text"
  | "unsupported";

const MARKDOWN_EXTENSIONS = new Set(["md", "mdx", "markdown"]);
const JSON_EXTENSIONS = new Set(["json"]);

/**
 * Anything we are happy to render as plain monospace text: data files, config,
 * logs, and the common source extensions an agent writes. Binary formats stay
 * out so they fall through to the "open externally" fallback.
 */
const TEXT_EXTENSIONS = new Set([
  "bash",
  "c",
  "cc",
  "cfg",
  "conf",
  "cpp",
  "cs",
  "css",
  "csv",
  "diff",
  "env",
  "go",
  "gql",
  "graphql",
  "h",
  "hcl",
  "hpp",
  "ini",
  "java",
  "jsonl",
  "js",
  "jsx",
  "kt",
  "log",
  "lua",
  "mjs",
  "patch",
  "php",
  "pl",
  "properties",
  "proto",
  "py",
  "rb",
  "rs",
  "scss",
  "sh",
  "sql",
  "swift",
  "tf",
  "toml",
  "ts",
  "tsv",
  "tsx",
  "txt",
  "xml",
  "yaml",
  "yml",
  "zsh",
]);

/** Pretty-printing a huge payload costs more than it helps; show it raw. */
const MAX_JSON_PRETTY_PRINT_CHARS = 512 * 1024;

function extension(fileName: string): string {
  const dot = fileName.lastIndexOf(".");
  return dot === -1 ? "" : fileName.slice(dot + 1).toLowerCase();
}

export function artifactPreviewKind(fileName: string): ArtifactPreviewKind {
  if (isRasterImageFile(fileName)) return "image";
  const ext = extension(fileName);
  if (MARKDOWN_EXTENSIONS.has(ext)) return "markdown";
  if (ext === "html" || ext === "htm") return "html";
  if (JSON_EXTENSIONS.has(ext)) return "json";
  if (TEXT_EXTENSIONS.has(ext)) return "text";
  return "unsupported";
}

/** Preview kinds whose renderer needs the file body, not just its URL. */
export function artifactPreviewNeedsText(kind: ArtifactPreviewKind): boolean {
  return (
    kind === "markdown" || kind === "html" || kind === "json" || kind === "text"
  );
}

/**
 * Indents JSON for reading. Invalid or oversized payloads pass through
 * untouched — a preview that shows the raw bytes beats an error screen.
 */
export function formatJsonForPreview(raw: string): string {
  if (raw.length > MAX_JSON_PRETTY_PRINT_CHARS) return raw;
  try {
    return JSON.stringify(JSON.parse(raw), null, 2);
  } catch {
    return raw;
  }
}

export function formatArtifactSize(size: number | undefined): string | null {
  if (size === undefined) return null;
  if (size < 1_000) return `${size} B`;
  if (size < 1_000_000) return `${Math.round(size / 1_000)} KB`;
  return `${(size / 1_000_000).toFixed(1)} MB`;
}
