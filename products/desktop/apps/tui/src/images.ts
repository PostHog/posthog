import { readFileSync } from "node:fs";
import { extname, isAbsolute } from "node:path";
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
