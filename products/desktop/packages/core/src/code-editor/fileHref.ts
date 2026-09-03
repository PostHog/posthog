export interface FileHrefTarget {
  /** Absolute, or relative to the task's working directory. */
  path: string;
  line: number | null;
}

const SCHEME_RE = /^[a-zA-Z][a-zA-Z\d+.-]*:/;
const FILE_SCHEME_RE = /^file:/i;
// `path/to/file.ts:12`, `path/to/file.ts:12-40`, and `path/to/file.ts#L12`.
const LINE_SUFFIX_RE = /^(.*[^/])(?::(\d+)(?:-\d+)?|#L(\d+))$/;
const LINE_FRAGMENT_RE = /^#L\d+$/;
const WINDOWS_DRIVE_RE = /^\/[a-zA-Z]:/;

function splitLineSuffix(path: string): FileHrefTarget {
  const match = LINE_SUFFIX_RE.exec(path);
  if (!match) return { path, line: null };
  const line = Number.parseInt(match[2] ?? match[3], 10);
  return { path: match[1], line: line > 0 ? line : null };
}

function pathFromFileUrl(href: string): FileHrefTarget | null {
  try {
    const url = new URL(href);
    // `file://host/share` names another machine, which this app cannot read.
    if (url.hostname && url.hostname !== "localhost") return null;
    // Split the line off the raw text. `#L12` sits in the fragment, outside
    // the pathname, and a percent-encoded `:` or `#` belongs to the filename.
    const target = splitLineSuffix(
      LINE_FRAGMENT_RE.test(url.hash) ? url.pathname + url.hash : url.pathname,
    );
    const path = decodeURIComponent(target.path);
    return {
      path: WINDOWS_DRIVE_RE.test(path) ? path.slice(1) : path,
      line: target.line,
    };
  } catch {
    return null;
  }
}

/**
 * The local file a markdown href names, or null when the href belongs to the
 * browser or to the page itself.
 *
 * An agent writes a file target either as a `file://` URL or as a bare path,
 * neither of which a browser can open: a bare path resolves against the app's
 * own origin, which is where the 404 comes from. Every other scheme —
 * `http`, `mailto`, `posthog-code`, `evidence` — keeps its existing handling,
 * and so does a `#fragment` inside the rendered document.
 */
export function parseFileHref(
  href: string | undefined | null,
): FileHrefTarget | null {
  const trimmed = href?.trim();
  if (!trimmed) return null;
  if (trimmed.startsWith("#") || trimmed.startsWith("?")) return null;
  if (FILE_SCHEME_RE.test(trimmed)) return pathFromFileUrl(trimmed);
  if (SCHEME_RE.test(trimmed)) return null;
  // A protocol-relative URL (`//example.com/x`) is a web page, not a path.
  if (trimmed.startsWith("//")) return null;
  return splitLineSuffix(trimmed.replace(/^\.\//, ""));
}
