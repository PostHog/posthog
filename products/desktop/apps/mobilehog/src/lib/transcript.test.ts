import type { StoredLogEntry } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import { type Block, foldEntries, promptPhotos } from "./transcript";

const photoUri = (runId: string, artifactId: string, name: string) =>
  `file:///tmp/workspace/.posthog/attachments/${runId}/${artifactId}/${name}`;

function promptEntry(prompt: unknown[]): StoredLogEntry {
  return {
    type: "notification",
    notification: { id: 1, method: "session/prompt", params: { prompt } },
  };
}

function userChunk(content: Record<string, unknown>): StoredLogEntry {
  return {
    type: "notification",
    notification: {
      method: "session/update",
      params: { update: { sessionUpdate: "user_message_chunk", content } },
    },
  };
}

const photoPrompt = [
  { type: "text", text: "what is this?" },
  {
    type: "resource_link",
    uri: photoUri("run-1", "artifact-1", "IMG_0001.jpg"),
    name: "IMG_0001.jpg",
    mimeType: "image/jpeg",
  },
];

// What the agent logs for a turn with a photo: the prompt, then its echo.
const photoTurn = [
  promptEntry(photoPrompt),
  userChunk({ type: "text", text: "what is this?" }),
  userChunk(photoPrompt[1]),
];

const photo = {
  runId: "run-1",
  artifactId: "artifact-1",
  name: "IMG_0001.jpg",
};

describe("promptPhotos", () => {
  it("reads photos from visible attachment links and skips other files", () => {
    const result = promptPhotos([
      { type: "text", text: "look", _meta: { ui: { hidden: true } } },
      { type: "text", text: "at these" },
      {
        type: "resource_link",
        uri: photoUri("run-1", "artifact-1", "IMG_0001.HEIC"),
        name: "IMG_0001.HEIC",
      },
      {
        type: "resource_link",
        uri: photoUri("run-1", "artifact-3", "IMG_0002.jpg"),
        name: "IMG_0002.jpg",
        _meta: { ui: { hidden: true } },
      },
      {
        type: "resource_link",
        uri: photoUri("run-1", "artifact-2", "notes.pdf"),
        name: "notes.pdf",
      },
      { type: "resource_link", uri: "file:///repo/cat.png", name: "cat.png" },
    ]);

    expect(result).toEqual({
      text: "at these",
      texts: ["at these"],
      photos: [
        { runId: "run-1", artifactId: "artifact-1", name: "IMG_0001.HEIC" },
      ],
    });
  });
});

describe("foldEntries with photos", () => {
  it("rebuilds a user message with its photos from the log", () => {
    const result = foldEntries([], photoTurn, new Set());

    expect(result.blocks).toEqual([
      expect.objectContaining({
        kind: "user",
        text: "what is this?",
        photos: [photo],
      }),
    ]);
    expect(result.externalUserMessages).toBe(1);
  });

  it("rebuilds a photo-only message", () => {
    const result = foldEntries(
      [],
      [promptEntry([photoPrompt[1]]), userChunk(photoPrompt[1])],
      new Set(),
    );

    expect(result.blocks).toEqual([
      expect.objectContaining({ kind: "user", text: "", photos: [photo] }),
    ]);
  });

  it("adds the photos to a message sent from this device", () => {
    const sent: Block = {
      kind: "user",
      id: "local-1",
      text: "what is this?",
      images: ["file:///picker/IMG_0001.jpg"],
    };
    const echoes = new Set(["what is this?"]);

    const result = foldEntries([sent], photoTurn, echoes);

    expect(result.blocks).toEqual([{ ...sent, photos: [photo] }]);
    expect(result.externalUserMessages).toBe(0);
    expect(echoes.size).toBe(0);
  });

  it("keeps photos already known for a sent message", () => {
    const known = { ...photo, artifactId: "artifact-9" };
    const sent: Block = {
      kind: "user",
      id: "local-1",
      text: "what is this?",
      photos: [known],
    };

    const result = foldEntries([sent], photoTurn, new Set(["what is this?"]));

    expect(result.blocks).toEqual([sent]);
  });

  it("clears the echo of a photo-only message sent from this device", () => {
    const sent: Block = { kind: "user", id: "local-1", text: "" };
    const echoes = new Set([""]);

    const result = foldEntries([sent], [promptEntry([photoPrompt[1]])], echoes);

    expect(result.blocks).toEqual([{ ...sent, photos: [photo] }]);
    expect(echoes.size).toBe(0);
  });

  it("matches the prompt and its echo across batches", () => {
    const echoes = new Set<string>();
    const first = foldEntries([], [promptEntry(photoPrompt)], echoes);
    const second = foldEntries(first.blocks, photoTurn.slice(1), echoes);

    expect(second.blocks).toHaveLength(1);
    expect(second.externalUserMessages).toBe(0);
  });

  it("leaves text-only prompts to the message echo", () => {
    const result = foldEntries(
      [],
      [
        promptEntry([{ type: "text", text: "hello" }]),
        userChunk({ type: "text", text: "hello" }),
      ],
      new Set(),
    );

    expect(result.blocks).toEqual([
      expect.objectContaining({ kind: "user", text: "hello" }),
    ]);
    expect(result.blocks[0]).not.toHaveProperty("photos");
  });
});
