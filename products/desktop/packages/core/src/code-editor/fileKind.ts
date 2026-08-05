import { getFileExtension } from "@posthog/shared";

const MARKDOWN_EXTENSIONS = new Set(["md", "markdown"]);
const HTML_EXTENSIONS = new Set(["html", "htm"]);

export type RenderableKind = "markdown" | "html";

export function isMarkdownFile(filename: string): boolean {
  return MARKDOWN_EXTENSIONS.has(getFileExtension(filename));
}

export function isHtmlFile(filename: string): boolean {
  return HTML_EXTENSIONS.has(getFileExtension(filename));
}

/**
 * The inline preview a file supports when opened from the file tree, or null if
 * it should open as plain source. Add a kind here (plus a renderer branch in
 * CodeEditorPanel) to make another file type previewable.
 */
export function getRenderableKind(filename: string): RenderableKind | null {
  if (isMarkdownFile(filename)) {
    return "markdown";
  }
  if (isHtmlFile(filename)) {
    return "html";
  }
  return null;
}
