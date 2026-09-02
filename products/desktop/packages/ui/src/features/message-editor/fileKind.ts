/**
 * A file's extension, dotted and lowercased, for the face of an attachment
 * square (`.md`, `.json`). Null when there is nothing useful to show — a
 * dotfile or an extensionless name — so callers can fall back to a glyph.
 */
export function fileExtensionLabel(filename: string): string | null {
  // `lastIndexOf` over split: a dotfile (`.env`) has no extension, and a
  // multi-dot name (`a.test.ts`) is typed by its last segment.
  const dot = filename.lastIndexOf(".");
  if (dot <= 0 || dot === filename.length - 1) return null;
  return `.${filename.slice(dot + 1).toLowerCase()}`;
}
