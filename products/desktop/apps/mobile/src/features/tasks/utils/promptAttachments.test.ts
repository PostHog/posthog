import { describe, expect, it } from "vitest";
import type { SessionEvent } from "../types";
import {
  extractSessionPromptAttachments,
  reinjectPromptAttachments,
} from "./promptAttachments";

const CLOUD_IMAGE_URI =
  "file:///tmp/workspace/.posthog/attachments/run-123/artifact-456/screenshot.png";
const CLOUD_DOC_URI =
  "file:///tmp/workspace/.posthog/attachments/run-123/artifact-789/notes.pdf";

function promptEvent(prompt: unknown[]): SessionEvent {
  return {
    type: "acp_message",
    direction: "client",
    ts: 1,
    message: { id: 1, method: "session/prompt", params: { prompt } },
  };
}

function userChunk(text: string): SessionEvent {
  return {
    type: "session_update",
    ts: 2,
    notification: {
      update: {
        sessionUpdate: "user_message_chunk",
        content: { type: "text", text },
      },
    },
  };
}

describe("extractSessionPromptAttachments", () => {
  it("extracts a cloud image attachment from a resource_link block", () => {
    const result = extractSessionPromptAttachments({
      method: "session/prompt",
      params: {
        prompt: [
          { type: "text", text: "what is this?" },
          {
            type: "resource_link",
            uri: CLOUD_IMAGE_URI,
            name: "screenshot.png",
          },
        ],
      },
    });

    expect(result).toEqual({
      text: "what is this?",
      attachments: [
        {
          kind: "image",
          uri: CLOUD_IMAGE_URI,
          fileName: "screenshot.png",
          cloudArtifact: { runId: "run-123", artifactId: "artifact-456" },
        },
      ],
    });
  });

  it("marks non-image cloud attachments as documents", () => {
    const result = extractSessionPromptAttachments({
      method: "session/prompt",
      params: { prompt: [{ type: "resource_link", uri: CLOUD_DOC_URI }] },
    });

    expect(result?.attachments[0]).toMatchObject({
      kind: "document",
      fileName: "notes.pdf",
    });
  });

  it("ignores hidden text blocks when reconstructing prompt text", () => {
    const result = extractSessionPromptAttachments({
      method: "session/prompt",
      params: {
        prompt: [
          { type: "text", text: "visible" },
          { type: "text", text: "hidden", _meta: { ui: { hidden: true } } },
          {
            type: "resource_link",
            uri: CLOUD_IMAGE_URI,
            name: "screenshot.png",
          },
        ],
      },
    });

    expect(result?.text).toBe("visible");
  });

  it("keeps ordinary file attachments that carry no cloud artifact", () => {
    const result = extractSessionPromptAttachments({
      method: "session/prompt",
      params: { prompt: [{ type: "image", uri: "file:///tmp/local.png" }] },
    });

    expect(result?.attachments).toEqual([
      { kind: "image", uri: "file:///tmp/local.png", fileName: "local.png" },
    ]);
  });

  it("renders an inline base64 image from its data preview", () => {
    const result = extractSessionPromptAttachments({
      method: "session/prompt",
      params: {
        prompt: [
          { type: "image", mimeType: "image/png", data: "AAAA" },
          { type: "text", text: "look" },
        ],
      },
    });

    expect(result?.attachments).toEqual([
      {
        kind: "image",
        uri: "data:image/png;base64,AAAA",
        fileName: "image.png",
      },
    ]);
  });

  it("deduplicates attachments that appear more than once in one prompt", () => {
    const result = extractSessionPromptAttachments({
      method: "session/prompt",
      params: {
        prompt: [
          { type: "resource_link", uri: CLOUD_IMAGE_URI, name: "shot.png" },
          { type: "resource_link", uri: CLOUD_IMAGE_URI, name: "shot.png" },
        ],
      },
    });

    expect(result?.attachments).toHaveLength(1);
  });

  it.each([
    { name: "non-prompt method", message: { method: "session/update" } },
    {
      name: "prompt without attachments",
      message: {
        method: "session/prompt",
        params: { prompt: [{ type: "text", text: "hi" }] },
      },
    },
  ])("returns null for $name", ({ message }) => {
    expect(extractSessionPromptAttachments(message)).toBeNull();
  });
});

describe("reinjectPromptAttachments", () => {
  it("reattaches attachments to the matching user_message_chunk", () => {
    const events: SessionEvent[] = [
      promptEvent([
        { type: "text", text: "what is this?" },
        { type: "resource_link", uri: CLOUD_IMAGE_URI, name: "screenshot.png" },
      ]),
      userChunk("what is this?"),
    ];

    reinjectPromptAttachments(events);

    const chunk = events[1];
    expect(
      chunk.type === "session_update" && chunk.notification.update?.attachments,
    ).toEqual([
      {
        kind: "image",
        uri: CLOUD_IMAGE_URI,
        fileName: "screenshot.png",
        cloudArtifact: { runId: "run-123", artifactId: "artifact-456" },
      },
    ]);
  });

  it("leaves ordinary user messages without attachments as-is", () => {
    const events: SessionEvent[] = [userChunk("no attachments here")];

    reinjectPromptAttachments(events);

    const chunk = events[0];
    expect(
      chunk.type === "session_update" && chunk.notification.update?.attachments,
    ).toBeUndefined();
  });

  it("matches identical prompt texts in FIFO order", () => {
    const secondUri =
      "file:///tmp/workspace/.posthog/attachments/run-123/artifact-999/second.png";
    const events: SessionEvent[] = [
      promptEvent([
        { type: "text", text: "same" },
        { type: "resource_link", uri: CLOUD_IMAGE_URI, name: "first.png" },
      ]),
      promptEvent([
        { type: "text", text: "same" },
        { type: "resource_link", uri: secondUri, name: "second.png" },
      ]),
      userChunk("same"),
      userChunk("same"),
    ];

    reinjectPromptAttachments(events);

    const first = events[2];
    const second = events[3];
    expect(
      first.type === "session_update" &&
        first.notification.update?.attachments?.[0]?.fileName,
    ).toBe("first.png");
    expect(
      second.type === "session_update" &&
        second.notification.update?.attachments?.[0]?.fileName,
    ).toBe("second.png");
  });
});
