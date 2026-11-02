import { createHash } from "node:crypto";
import {
  existsSync,
  mkdirSync,
  readFileSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { homedir } from "node:os";
import { basename, dirname, extname, isAbsolute, join } from "node:path";
import type { ImageContent } from "@earendil-works/pi-ai";

// A file dropped on a chat that is not an image: sent by path, since the agent reads it from disk or the sandbox
// gets it uploaded, so its bytes never pass through the composer.
export interface DroppedFile {
  type: "file";
  path: string;
  name: string;
}
export type Attachment = ImageContent | DroppedFile;

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

// Every file in a drop: an image by its bytes, anything else by its path. A folder is skipped.
export function droppedAttachments(sequence: string): Attachment[] {
  const attachments: Attachment[] = [];
  for (const path of droppedPaths(sequence)) {
    const mimeType = MIME_TYPES[extname(path).toLowerCase()];
    try {
      if (!statSync(path).isFile()) continue;
      attachments.push(
        mimeType
          ? {
              type: "image",
              data: readFileSync(path).toString("base64"),
              mimeType,
            }
          : { type: "file", path, name: basename(path) },
      );
    } catch {}
  }
  return attachments;
}

// A local agent reads a dropped file where it sits, so the message names its path in place of the marker.
export function withFilePaths(
  message: string,
  attachments: Attachment[],
): string {
  const files = attachments.filter((a): a is DroppedFile => a.type === "file");
  if (files.length === 0) return message;
  let index = 0;
  return message.replace(
    /\[File #\d+: [^\]]*\]/g,
    (marker) => files[index++]?.path ?? marker,
  );
}

export const isImage = (attachment: Attachment): attachment is ImageContent =>
  attachment.type === "image";

// The path a cloud upload reads an attachment from: a dropped file's own, or the copy the TUI keeps of an image.
export const fileOf = (attachment: Attachment): string =>
  isImage(attachment) ? savedImage(attachment) : attachment.path;

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
