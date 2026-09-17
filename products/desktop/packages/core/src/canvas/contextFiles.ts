import type { ContextLink } from "./contextDocument";

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

export function newFileContent(name: string, body = ""): string {
  if (FRONTMATTER_START.test(body)) return body;
  const title = fileTitle(name);
  const text = body.trim() ? body.trimEnd() : `# ${title}\n`;
  return `---\nsummary: ${title}\nstatus: active\n---\n\n${text}\n`;
}

export const UPLOAD_ACCEPT = ".md,.markdown,.txt";
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
