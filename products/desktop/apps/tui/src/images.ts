import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, extname, isAbsolute, join } from "node:path";
import type { ImageContent } from "@earendil-works/pi-ai";

const PASTE_START = "\u001b[200~";
const PASTE_END = "\u001b[201~";
const MIME_TYPES: Record<string, string> = {
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".gif": "image/gif",
  ".webp": "image/webp",
};

// Files dropped on the terminal arrive as their paths separated by spaces, each quoted or with its spaces
// escaped, as one bracketed paste or (macOS Terminal) as bare keys in one burst. Only an ASCII space separates
// paths: a macOS screenshot's name holds a narrow no-break space before am/pm, which Terminal never escapes. A
// piece that is no file is joined to the next and tried again. Anything else, or a path that is not absolute,
// is text; so is a bare burst that names no file, since a typed "/search" arrives as one burst too.
export function droppedPaths(sequence: string): string[] {
  const bracketed =
    sequence.startsWith(PASTE_START) && sequence.endsWith(PASTE_END);
  const pasted = (
    bracketed ? sequence.slice(PASTE_START.length, -PASTE_END.length) : sequence
  ).trim();
  if (pasted.includes("\n")) return [];
  const pieces: string[] = [];
  const word = /'([^']*)'|"([^"]*)"|((?:\\.|[^ '"])+)/g;
  for (const match of pasted.matchAll(word)) {
    pieces.push(match[1] ?? match[2] ?? match[3].replace(/\\(.)/g, "$1"));
  }
  const paths: string[] = [];
  let pending = "";
  for (const piece of pieces) {
    pending = pending ? `${pending} ${piece}` : piece;
    if (existsSync(pending)) {
      paths.push(pending);
      pending = "";
    }
  }
  if (pending) {
    if (!bracketed) return [];
    paths.push(pending);
  }
  return paths.length > 0 && paths.every(isAbsolute) ? paths : [];
}

export function droppedImages(sequence: string): ImageContent[] {
  const images: ImageContent[] = [];
  for (const path of droppedPaths(sequence)) {
    const mimeType = MIME_TYPES[extname(path).toLowerCase()];
    if (!mimeType) continue;
    try {
      images.push({
        type: "image",
        data: readFileSync(path).toString("base64"),
        mimeType,
      });
    } catch {}
  }
  return images;
}

// Sent images are kept with the TUI's other state, by a hash of their bytes, so a click can open one after its source is gone.
export const IMAGES_DIR = join(homedir(), ".config", "posthog-tui", "images");
const EXTENSIONS: Record<string, string> = Object.fromEntries(
  Object.entries(MIME_TYPES).map(([extension, mimeType]) => [
    mimeType,
    extension,
  ]),
);
const saved = new Map<string, string>();

// The file holding a sent image, written the first time it is asked for.
export function savedImage(image: { data: string; mimeType: string }): string {
  const known = saved.get(image.data);
  if (known) return known;
  const bytes = Buffer.from(image.data, "base64");
  const name = createHash("sha256").update(bytes).digest("hex").slice(0, 32);
  const path = join(
    IMAGES_DIR,
    `${name}${EXTENSIONS[image.mimeType] ?? ".png"}`,
  );
  if (!existsSync(path)) {
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, bytes);
  }
  saved.set(image.data, path);
  return path;
}
