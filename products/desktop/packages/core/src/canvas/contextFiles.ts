import type { ContextLink } from "./contextDocument";

/**
 * Extra Markdown files of a space live in the context wiki, in a folder named
 * after the space's own page: `projects/1/spaces/checkout.md` keeps its files
 * under `projects/1/spaces/checkout/`. CONTEXT.md lists each one in its
 * Reading section by that path, which is how a row knows it opens an editor
 * rather than a browser.
 */
export function spaceFilesFolder(wikiPath: string): string {
  return `${wikiPath.replace(/\.md$/i, "")}/`;
}

export function isSpaceFile(link: ContextLink, folder: string | null): boolean {
  return (
    folder !== null &&
    link.target.startsWith(folder) &&
    link.target.toLowerCase().endsWith(".md")
  );
}

export function fileDisplayName(target: string): string {
  return target.split("/").pop() ?? target;
}

/**
 * The wiki accepts a narrow set of path characters, so a name a person typed
 * (or a file's original name) is reduced to lowercase words joined by dashes
 * and given the `.md` the wiki requires. Returns null when nothing usable is
 * left.
 */
export function fileNameToPath(folder: string, name: string): string | null {
  const stem = name
    .trim()
    .replace(/\.(md|markdown|txt)$/i, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return stem ? `${folder}${stem}.md` : null;
}

export function fileTitle(name: string): string {
  const stem = name.trim().replace(/\.(md|markdown|txt)$/i, "");
  return stem.replace(/[-_]+/g, " ").trim() || "Untitled";
}

const FRONTMATTER_START = /^---\r?\n/;

/**
 * Every page under the wiki's projects tree needs a one-line summary and a
 * status, so a new file starts with both. Text that already carries
 * frontmatter is kept as it is and the wiki's own check says what is missing.
 */
export function newFileContent(name: string, body = ""): string {
  if (FRONTMATTER_START.test(body)) return body;
  const title = fileTitle(name);
  const text = body.trim() ? body.trimEnd() : `# ${title}\n`;
  return `---\nsummary: ${title}\nstatus: active\n---\n\n${text}\n`;
}

export const UPLOAD_ACCEPT = ".md,.markdown,.txt";
/** Well under the wiki's page cap, and past what anyone types by hand. */
export const UPLOAD_MAX_BYTES = 1_000_000;

export function isUploadableFile(file: {
  name: string;
  type: string;
}): boolean {
  const lower = file.name.toLowerCase();
  return (
    UPLOAD_ACCEPT.split(",").some((ext) => lower.endsWith(ext)) ||
    file.type.startsWith("text/")
  );
}
