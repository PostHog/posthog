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

// Files dropped on the terminal arrive as one paste of their paths, each quoted or with its spaces escaped, and
// separated by spaces. Anything else pasted, or a path that is not absolute, is text.
export function droppedPaths(sequence: string): string[] {
  if (!sequence.startsWith(PASTE_START) || !sequence.endsWith(PASTE_END))
    return [];
  const pasted = sequence.slice(PASTE_START.length, -PASTE_END.length).trim();
  if (pasted.includes("\n")) return [];
  const paths: string[] = [];
  const word = /'([^']*)'|"([^"]*)"|((?:\\.|[^\s'"])+)/g;
  for (const match of pasted.matchAll(word)) {
    paths.push(match[1] ?? match[2] ?? match[3].replace(/\\(.)/g, "$1"));
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
