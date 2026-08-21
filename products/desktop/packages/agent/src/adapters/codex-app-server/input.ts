import { fileURLToPath } from "node:url";
import type { ContentBlock } from "@agentclientprotocol/sdk";

/**
 * Codex app-server `UserInput`, narrowed to the three variants an ACP prompt
 * can produce (`text`, remote `image`, `localImage`).
 */
export type CodexUserInput =
  | { type: "text"; text: string; text_elements: [] }
  | { type: "image"; url: string }
  | { type: "localImage"; path: string };

function textInput(text: string): CodexUserInput {
  return { type: "text", text, text_elements: [] };
}

/** A `file://` resource is surfaced as its path so codex reads it from disk. */
function resourceLinkText(uri: string): string {
  if (uri.startsWith("file://")) {
    try {
      return `Attached workspace file (read it from disk): ${fileURLToPath(uri)}`;
    } catch {
      return `Attached file: ${uri}`;
    }
  }
  return `Attached resource: ${uri}`;
}

/**
 * Maps ACP prompt content blocks to codex app-server `UserInput[]`. Text passes through;
 * images map to `image`/`localImage`; `file://` resources become path notes and non-file
 * resource text is inlined as a trailing `<context ref>` block. Audio/blob/malformed are dropped.
 */
export function toCodexInput(prompt: ContentBlock[]): CodexUserInput[] {
  const input: CodexUserInput[] = [];
  const context: string[] = [];
  for (const block of prompt) {
    if (block.type === "text") {
      input.push(textInput(block.text));
      continue;
    }
    if (block.type === "image") {
      const mapped = imageToCodexInput(block);
      if (mapped) {
        input.push(mapped);
      }
      continue;
    }
    if (block.type === "resource_link") {
      input.push(textInput(resourceLinkText(block.uri)));
      continue;
    }
    if (block.type === "resource" && "text" in block.resource) {
      const uri = block.resource.uri ?? "";
      if (uri.startsWith("file://")) {
        input.push(textInput(resourceLinkText(uri)));
        continue;
      }
      if (uri) {
        input.push(textInput(uri));
      }
      context.push(
        `<context ref="${uri}">\n${block.resource.text}\n</context>`,
      );
    }
  }
  if (context.length > 0) {
    input.push(textInput(context.join("\n")));
  }
  return input;
}

/**
 * Prefer inline base64 (as a data URL); else fall back to the `uri`:
 * `http(s)` → remote `image`, `file://` → `localImage`.
 */
function imageToCodexInput(block: {
  data: string;
  mimeType: string;
  uri?: string | null;
}): CodexUserInput | undefined {
  if (block.data) {
    return {
      type: "image",
      url: `data:${block.mimeType};base64,${block.data}`,
    };
  }
  const uri = block.uri;
  if (!uri) {
    return undefined;
  }
  if (uri.startsWith("http://") || uri.startsWith("https://")) {
    return { type: "image", url: uri };
  }
  if (uri.startsWith("file://")) {
    try {
      return { type: "localImage", path: fileURLToPath(uri) };
    } catch {
      return undefined;
    }
  }
  return undefined;
}
