/**
 * Cross-platform check for absolute file paths.
 * Handles both Unix (/path) and Windows (C:\path) formats.
 */
export function isAbsolutePath(filePath: string): boolean {
  return (
    filePath.startsWith("/") ||
    // Windows drive, e.g. C:\path or C:/path
    /^[a-zA-Z]:/.test(filePath) ||
    // Windows UNC, e.g. \\server\share\path
    filePath.startsWith("\\\\") ||
    // UNC normalized to forward slashes, e.g. //server/share/path
    filePath.startsWith("//")
  );
}

/**
 * Convert an absolute file path to a path relative to the repo root.
 * Normalizes separators to forward slashes before comparison so this
 * works on both Unix and Windows.
 */
export function toRelativePath(filePath: string, repoPath: string): string {
  const normalized = filePath.replaceAll("\\", "/");
  const normalizedRepo = repoPath.replaceAll("\\", "/");
  return normalized.startsWith(`${normalizedRepo}/`)
    ? normalized.slice(normalizedRepo.length + 1)
    : normalized;
}

export function expandTildePath(path: string): string {
  if (typeof path !== "string") return String(path);
  if (!path.startsWith("~")) return path;
  // In renderer context, we can't access process.env directly
  // For now, return the path as-is since the main process will handle expansion
  // Or we could use a pattern like /Users/username or /home/username
  // The actual expansion should happen on the Electron main side
  return path;
}

export function compactHomePath(text: string): string {
  if (typeof text !== "string") return String(text);
  return text
    .replace(/\/Users\/[^/\s]+/g, "~")
    .replace(/\/home\/[^/\s]+/g, "~");
}

export function getFileName(filePath: string): string {
  const parts = filePath.split(/[\\/]/);
  return parts[parts.length - 1] || filePath;
}

export function getFileExtension(filePath: string): string {
  const name = getFileName(filePath);
  const lastDot = name.lastIndexOf(".");
  return lastDot >= 0 ? name.slice(lastDot + 1).toLowerCase() : "";
}

/**
 * Convert a local file path to a `file://` URI.
 * Renderer-safe (no `node:*` imports) and supports Windows drive and UNC paths.
 */
export function pathToFileUri(filePath: string): string {
  if (filePath.startsWith("file://")) {
    return filePath;
  }

  // Normalize Windows separators for string processing.
  const normalized = filePath.replaceAll("\\", "/");

  // UNC path: \\server\share\dir\file.txt → file://server/share/dir/file.txt
  if (normalized.startsWith("//")) {
    const withoutPrefix = normalized.slice(2);
    const parts = withoutPrefix.split("/").filter(Boolean);
    const host = parts.shift() ?? "";
    const encodedPath = parts.map(encodeURIComponent).join("/");
    return `file://${host}/${encodedPath}`;
  }

  // Drive path: C:\dir\file.txt or C:/dir/file.txt → file:///C:/dir/file.txt
  const drive = normalized.match(/^([A-Za-z]):\/(.*)$/);
  if (drive) {
    const letter = drive[1].toUpperCase();
    const rest = drive[2];
    const encoded = rest
      .split("/")
      .filter((segment) => segment.length > 0)
      .map(encodeURIComponent)
      .join("/");
    return `file:///${letter}:/${encoded}`;
  }

  // POSIX absolute path: /tmp/test.txt → file:///tmp/test.txt
  if (normalized.startsWith("/")) {
    const encoded = normalized.split("/").map(encodeURIComponent).join("/");
    return `file://${encoded}`;
  }

  // Fallback.
  const encoded = normalized.split("/").map(encodeURIComponent).join("/");
  return `file://${encoded}`;
}
