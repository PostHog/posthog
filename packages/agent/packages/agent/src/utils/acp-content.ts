import type { ContentBlock, ToolCallContent } from "@agentclientprotocol/sdk";

export function text(value: string): ContentBlock {
  return { type: "text", text: value };
}

export function image(
  data: string,
  mimeType: string,
  uri?: string,
): ContentBlock {
  return { type: "image", data, mimeType, uri };
}

// The API rejects replayed history containing empty content blocks with a 400
// ("text content blocks must be non-empty").
export function isEmptyContentBlock(block: unknown): boolean {
  const candidate = block as
    | { type?: string; text?: string; thinking?: string }
    | null
    | undefined;
  if (candidate?.type === "text") return !candidate.text;
  if (candidate?.type === "thinking") return !candidate.thinking;
  return false;
}

export function resourceLink(
  uri: string,
  name: string,
  options?: {
    mimeType?: string;
    title?: string;
    description?: string;
    size?: number | null;
  },
): ContentBlock {
  return {
    type: "resource_link",
    uri,
    name,
    ...options,
  };
}

class ToolContentBuilder {
  private items: ToolCallContent[] = [];

  text(value: string): this {
    this.items.push({ type: "content", content: text(value) });
    return this;
  }

  image(data: string, mimeType: string, uri?: string): this {
    this.items.push({ type: "content", content: image(data, mimeType, uri) });
    return this;
  }

  diff(path: string, oldText: string | null, newText: string): this {
    this.items.push({ type: "diff", path, oldText, newText });
    return this;
  }

  build(): ToolCallContent[] {
    return this.items;
  }
}

export function toolContent(): ToolContentBuilder {
  return new ToolContentBuilder();
}
