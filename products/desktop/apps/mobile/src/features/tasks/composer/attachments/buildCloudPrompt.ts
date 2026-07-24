import * as FileSystem from "expo-file-system/legacy";
import type { CloudPromptBlock, PendingAttachment } from "./types";

const MAX_EMBEDDED_TEXT_CHARS = 100_000;
const MAX_EMBEDDED_IMAGE_BYTES = 5 * 1024 * 1024;

const TEXT_MIME_PREFIXES = ["text/"];
const TEXT_MIME_TYPES = new Set([
  "application/json",
  "application/xml",
  "application/javascript",
  "application/typescript",
  "application/x-sh",
  "application/x-yaml",
  "application/x-toml",
]);
const TEXT_EXTENSIONS = new Set([
  "c",
  "cc",
  "cfg",
  "conf",
  "cpp",
  "cs",
  "css",
  "csv",
  "env",
  "gitignore",
  "go",
  "h",
  "hpp",
  "html",
  "ini",
  "java",
  "js",
  "json",
  "jsx",
  "log",
  "md",
  "mjs",
  "py",
  "rb",
  "rs",
  "scss",
  "sh",
  "sql",
  "svg",
  "toml",
  "ts",
  "tsx",
  "txt",
  "xml",
  "yaml",
  "yml",
  "zsh",
]);

function getExt(fileName: string): string {
  const dot = fileName.lastIndexOf(".");
  return dot >= 0 ? fileName.slice(dot + 1).toLowerCase() : "";
}

function isTextAttachment(mimeType: string, fileName: string): boolean {
  const mt = mimeType.toLowerCase();
  if (TEXT_MIME_PREFIXES.some((p) => mt.startsWith(p))) return true;
  if (TEXT_MIME_TYPES.has(mt)) return true;
  return TEXT_EXTENSIONS.has(getExt(fileName));
}

function getTextMimeType(fileName: string, fallback: string): string {
  const ext = getExt(fileName);
  switch (ext) {
    case "json":
      return "application/json";
    case "md":
      return "text/markdown";
    case "svg":
      return "image/svg+xml";
    case "xml":
      return "application/xml";
    default:
      return fallback.startsWith("text/") ? fallback : "text/plain";
  }
}

function truncateText(text: string): string {
  if (text.length <= MAX_EMBEDDED_TEXT_CHARS) return text;
  return `${text.slice(0, MAX_EMBEDDED_TEXT_CHARS)}\n\n[Attachment truncated to ${MAX_EMBEDDED_TEXT_CHARS.toLocaleString()} characters for this cloud prompt.]`;
}

function estimateBase64Bytes(base64: string): number {
  const padding = base64.endsWith("==") ? 2 : base64.endsWith("=") ? 1 : 0;
  return Math.floor((base64.length * 3) / 4) - padding;
}

async function buildBlock(att: PendingAttachment): Promise<CloudPromptBlock> {
  if (att.kind === "image") {
    const base64 = await FileSystem.readAsStringAsync(att.uri, {
      encoding: FileSystem.EncodingType.Base64,
    });
    if (estimateBase64Bytes(base64) > MAX_EMBEDDED_IMAGE_BYTES) {
      throw new Error(
        `${att.fileName} is too large for a cloud image attachment (max 5 MB).`,
      );
    }
    return {
      type: "image",
      data: base64,
      mimeType: att.mimeType || "image/jpeg",
      uri: `attachment://${att.fileName}`,
    };
  }

  // Document attachment — must be text-readable.
  if (!isTextAttachment(att.mimeType, att.fileName)) {
    throw new Error(
      `Cloud attachments support text and image files. Unsupported: ${att.fileName}`,
    );
  }
  const text = await FileSystem.readAsStringAsync(att.uri, {
    encoding: FileSystem.EncodingType.UTF8,
  });
  return {
    type: "resource",
    resource: {
      uri: `attachment://${att.fileName}`,
      text: truncateText(text),
      mimeType: getTextMimeType(att.fileName, att.mimeType),
    },
  };
}

/**
 * Reads each attachment from disk and assembles the cloud-prompt block array
 * the agent server expects. Throws if any individual attachment fails so the
 * caller can surface a single, attributable error to the user.
 */
export async function buildCloudPromptBlocks(
  text: string,
  attachments: PendingAttachment[],
): Promise<CloudPromptBlock[]> {
  const blocks: CloudPromptBlock[] = [];
  const trimmed = text.trim();
  if (trimmed) blocks.push({ type: "text", text: trimmed });
  for (const attachment of attachments) {
    blocks.push(await buildBlock(attachment));
  }
  if (blocks.length === 0) {
    throw new Error("Cloud prompt cannot be empty");
  }
  return blocks;
}
