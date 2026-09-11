import { describe, expect, it } from "vitest";
import {
  extractImageFileTags,
  extractPromptDisplayContent,
  makeAttachmentUri,
  parseAttachmentUri,
} from "./promptContent";

describe("promptContent", () => {
  it("builds unique attachment URIs for same-name files", () => {
    const firstUri = makeAttachmentUri("/tmp/one/README.md");
    const secondUri = makeAttachmentUri("/tmp/two/README.md");

    expect(firstUri).not.toBe(secondUri);
    expect(parseAttachmentUri(firstUri)).toEqual({
      id: firstUri,
      label: "README.md",
    });
    expect(parseAttachmentUri(secondUri)).toEqual({
      id: secondUri,
      label: "README.md",
    });
  });

  it("keeps duplicate file labels visible when attachment ids differ", () => {
    const firstUri = makeAttachmentUri("/tmp/one/README.md");
    const secondUri = makeAttachmentUri("/tmp/two/README.md");

    const result = extractPromptDisplayContent([
      { type: "text", text: "compare both" },
      {
        type: "resource",
        resource: { uri: firstUri, text: "first", mimeType: "text/markdown" },
      },
      {
        type: "resource",
        resource: {
          uri: secondUri,
          text: "second",
          mimeType: "text/markdown",
        },
      },
    ]);

    expect(result.text).toBe("compare both");
    expect(result.attachments).toEqual([
      { id: firstUri, label: "README.md" },
      { id: secondUri, label: "README.md" },
    ]);
  });

  it("extracts cloud resource_link attachments from file URIs", () => {
    const fileUri =
      "file:///tmp/workspace/.posthog/attachments/run-123/artifact-456/Receipt-2264-0277.pdf";

    const result = extractPromptDisplayContent([
      { type: "text", text: "what is this about?" },
      {
        type: "resource_link",
        uri: fileUri,
        name: "Receipt-2264-0277.pdf",
      },
    ]);

    expect(result.text).toBe("what is this about?");
    expect(result.attachments).toEqual([
      {
        id: fileUri,
        label: "Receipt-2264-0277.pdf",
        cloudArtifact: { runId: "run-123", artifactId: "artifact-456" },
      },
    ]);
  });

  it("extracts inline Pi images as previewable attachments", () => {
    const result = extractPromptDisplayContent([
      { type: "text", text: "what is in this image?" },
      {
        type: "image",
        data: "aW1hZ2U=",
        mimeType: "image/png",
        fileName: "screenshot.png",
      } as Parameters<typeof extractPromptDisplayContent>[0][number],
    ]);

    expect(result).toEqual({
      text: "what is in this image?",
      attachments: [
        {
          id: expect.stringMatching(/^inline-image:/),
          label: "screenshot.png",
          previewUrl: "data:image/png;base64,aW1hZ2U=",
        },
      ],
    });
  });

  it("does not mark ordinary file URIs as cloud artifacts", () => {
    const fileUri = "file:///tmp/screenshot.png";

    const result = extractPromptDisplayContent([
      { type: "resource_link", uri: fileUri, name: "screenshot.png" },
    ]);

    expect(result.attachments).toEqual([
      { id: fileUri, label: "screenshot.png" },
    ]);
  });

  it.each([
    {
      name: "lifts a composer image tag out of the text",
      text: 'look at this <file path="/tmp/posthog-code-clipboard/attachment-abc/clipboard.png" />',
      expected: {
        text: "look at this",
        attachments: [
          {
            id: "file:///tmp/posthog-code-clipboard/attachment-abc/clipboard.png",
            label: "clipboard.png",
          },
        ],
      },
    },
    {
      name: "keeps images outside the composer folder inline",
      text: 'see <file path="/Users/me/Pictures/secret.png" /> and <file path="src/logo.png" />',
      expected: {
        text: 'see <file path="/Users/me/Pictures/secret.png" /> and <file path="src/logo.png" />',
        attachments: [],
      },
    },
    {
      name: "keeps non-image composer files inline",
      text: 'see <file path="/tmp/posthog-code-clipboard/attachment-abc/notes.md" />',
      expected: {
        text: 'see <file path="/tmp/posthog-code-clipboard/attachment-abc/notes.md" />',
        attachments: [],
      },
    },
  ])("extractImageFileTags $name", ({ text, expected }) => {
    expect(extractImageFileTags(text)).toEqual(expected);
  });
});
