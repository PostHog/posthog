import type { ContentBlock } from "@agentclientprotocol/sdk";
import { describe, expect, it } from "vitest";
import { toCodexInput } from "./input";

describe("toCodexInput", () => {
  it("passes text blocks through with empty text_elements", () => {
    const prompt: ContentBlock[] = [
      { type: "text", text: "hello" },
      { type: "text", text: "world" },
    ];

    expect(toCodexInput(prompt)).toEqual([
      { type: "text", text: "hello", text_elements: [] },
      { type: "text", text: "world", text_elements: [] },
    ]);
  });

  it("maps a base64 image block to the codex image variant as a data URL", () => {
    const prompt: ContentBlock[] = [
      { type: "image", data: "AAAA", mimeType: "image/png" },
    ];

    expect(toCodexInput(prompt)).toEqual([
      { type: "image", url: "data:image/png;base64,AAAA" },
    ]);
  });

  it("maps an http(s) image URI to a remote image and file:// to localImage", () => {
    const prompt: ContentBlock[] = [
      {
        type: "image",
        data: "",
        mimeType: "image/png",
        uri: "https://x/y.png",
      },
      {
        type: "image",
        data: "",
        mimeType: "image/png",
        uri: "file:///tmp/pic.png",
      },
    ];

    expect(toCodexInput(prompt)).toEqual([
      { type: "image", url: "https://x/y.png" },
      { type: "localImage", path: "/tmp/pic.png" },
    ]);
  });

  it("drops only audio and unusable images, keeping text", () => {
    const prompt: ContentBlock[] = [
      { type: "text", text: "keep" },
      { type: "audio", data: "AAAA", mimeType: "audio/wav" },
      { type: "image", data: "", mimeType: "image/png", uri: "ftp://nope" },
    ];

    expect(toCodexInput(prompt)).toEqual([
      { type: "text", text: "keep", text_elements: [] },
    ]);
  });

  it("surfaces a file:// resource_link as its on-disk path", () => {
    const prompt: ContentBlock[] = [
      { type: "resource_link", uri: "file:///repo/doc.md", name: "doc" },
    ];

    expect(toCodexInput(prompt)).toEqual([
      {
        type: "text",
        text: "Attached workspace file (read it from disk): /repo/doc.md",
        text_elements: [],
      },
    ]);
  });

  it("inlines a non-file resource's text as a trailing <context> block", () => {
    const prompt: ContentBlock[] = [
      { type: "text", text: "use the snippet" },
      {
        type: "resource",
        resource: { uri: "https://x/snippet", text: "const a = 1;" },
      },
    ];

    expect(toCodexInput(prompt)).toEqual([
      { type: "text", text: "use the snippet", text_elements: [] },
      { type: "text", text: "https://x/snippet", text_elements: [] },
      {
        type: "text",
        text: '<context ref="https://x/snippet">\nconst a = 1;\n</context>',
        text_elements: [],
      },
    ]);
  });

  it("omits the bare-uri text block for a resource with no uri", () => {
    const prompt: ContentBlock[] = [
      {
        type: "resource",
        resource: { text: "inline snippet" },
      } as unknown as ContentBlock,
    ];

    expect(toCodexInput(prompt)).toEqual([
      {
        type: "text",
        text: '<context ref="">\ninline snippet\n</context>',
        text_elements: [],
      },
    ]);
  });

  it("surfaces a file:// resource as its path, not inline text", () => {
    const prompt: ContentBlock[] = [
      {
        type: "resource",
        resource: { uri: "file:///repo/a.ts", text: "stale on-disk copy" },
      },
    ];

    expect(toCodexInput(prompt)).toEqual([
      {
        type: "text",
        text: "Attached workspace file (read it from disk): /repo/a.ts",
        text_elements: [],
      },
    ]);
  });
});
