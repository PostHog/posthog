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

// A file dropped on the terminal arrives as a paste of its path, quoted or with its spaces escaped.
export function droppedPath(sequence: string): string | null {
  if (!sequence.startsWith(PASTE_START) || !sequence.endsWith(PASTE_END))
    return null;
  const pasted = sequence.slice(PASTE_START.length, -PASTE_END.length).trim();
  const path = /^(['"]).*\1$/.test(pasted)
    ? pasted.slice(1, -1)
    : pasted.replace(/\\(.)/g, "$1");
  return isAbsolute(path) && !path.includes("\n") ? path : null;
}

export function droppedImage(sequence: string): ImageContent | null {
  const path = droppedPath(sequence);
  const mimeType = path ? MIME_TYPES[extname(path).toLowerCase()] : undefined;
  if (!path || !mimeType) return null;
  try {
    return {
      type: "image",
      data: readFileSync(path).toString("base64"),
      mimeType,
    };
  } catch {
    return null;
  }
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
