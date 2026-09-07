import type { ContentBlock } from "@agentclientprotocol/sdk";
import { describe, expect, it } from "vitest";
import {
  combineQueuedCloudPrompts,
  promptToQueuedEditorContent,
} from "./cloudPrompt";

describe("cloudPrompt", () => {
  it("preserves attachment blocks when combining queued cloud prompts", () => {
    const prompt: ContentBlock[] = [
      { type: "text", text: "read this" },
      {
        type: "resource_link",
        uri: "file:///tmp/test.txt",
        name: "test.txt",
        mimeType: "text/plain",
      },
    ];

    expect(
      combineQueuedCloudPrompts([
        {
          content: "read this\n\nAttached files: test.txt",
          rawPrompt: prompt,
        },
      ]),
    ).toEqual(prompt);
  });

  it("restores queued editor content with attachments from prompt blocks", () => {
    const prompt: ContentBlock[] = [
      { type: "text", text: "read this" },
      {
        type: "resource_link",
        uri: "file:///tmp/test.txt",
        name: "test.txt",
        mimeType: "text/plain",
      },
    ];

    expect(promptToQueuedEditorContent(prompt)).toEqual({
      segments: [{ type: "text", text: "read this" }],
      attachments: [{ id: "/tmp/test.txt", label: "test.txt" }],
    });
  });
});
