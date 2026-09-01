import { isRasterImageFile } from "@posthog/shared";

export type ArtifactPreviewKind = "image" | "markdown" | "html" | "unsupported";

const MARKDOWN_EXTENSIONS = new Set(["md", "mdx", "markdown"]);

function extension(fileName: string): string {
  return fileName.split(".").pop()?.toLowerCase() ?? "";
}

export function artifactPreviewKind(fileName: string): ArtifactPreviewKind {
  if (isRasterImageFile(fileName)) return "image";
  const ext = extension(fileName);
  if (MARKDOWN_EXTENSIONS.has(ext)) return "markdown";
  if (ext === "html" || ext === "htm") return "html";
  return "unsupported";
}

export function formatArtifactSize(size: number | undefined): string | null {
  if (size === undefined) return null;
  if (size < 1_000) return `${size} B`;
  if (size < 1_000_000) return `${Math.round(size / 1_000)} KB`;
  return `${(size / 1_000_000).toFixed(1)} MB`;
}
