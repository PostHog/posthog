import { describe, expect, it, vi } from "vitest";
import type { PendingAttachment } from "./attachments/types";
import {
  type ComposerContent,
  isComposerEmpty,
  submitComposerMessage,
} from "./submitComposerMessage";

const attachment: PendingAttachment = {
  kind: "image",
  id: "a1",
  uri: "file://x.png",
  fileName: "x.png",
  mimeType: "image/png",
};

const submitted: ComposerContent = {
  text: "hello there",
  attachments: [attachment],
};

function createComposer(
  initial: ComposerContent = { text: "", attachments: [] },
) {
  let content = initial;
  return {
    get content() {
      return content;
    },
    clear: vi.fn(() => {
      content = { text: "", attachments: [] };
    }),
    restore: vi.fn((next: ComposerContent) => {
      content = next;
    }),
    isEmpty: () => isComposerEmpty(content),
  };
}

describe("isComposerEmpty", () => {
  const cases: Array<[ComposerContent, boolean]> = [
    [{ text: "", attachments: [] }, true],
    [{ text: "   ", attachments: [] }, true],
    [{ text: "hi", attachments: [] }, false],
    [{ text: "", attachments: [attachment] }, false],
  ];
  it.each(cases)("%o -> %s", (content, expected) => {
    expect(isComposerEmpty(content)).toBe(expected);
  });
});

describe("submitComposerMessage", () => {
  it("clears and stays cleared on a successful send", async () => {
    const composer = createComposer();

    await submitComposerMessage({
      submitted,
      clear: composer.clear,
      send: async () => true,
      isLatestSubmission: () => true,
      isEmpty: composer.isEmpty,
      restore: composer.restore,
    });

    expect(composer.clear).toHaveBeenCalledOnce();
    expect(composer.restore).not.toHaveBeenCalled();
    expect(composer.content).toEqual({ text: "", attachments: [] });
  });

  it("restores text and attachments when a send fails", async () => {
    const composer = createComposer();

    await submitComposerMessage({
      submitted,
      clear: composer.clear,
      send: async () => false,
      isLatestSubmission: () => true,
      isEmpty: composer.isEmpty,
      restore: composer.restore,
    });

    expect(composer.restore).toHaveBeenCalledWith(submitted);
    expect(composer.content).toEqual(submitted);
  });

  it("treats a thrown send as a failure and restores", async () => {
    const composer = createComposer();

    await submitComposerMessage({
      submitted,
      clear: composer.clear,
      send: async () => {
        throw new Error("network");
      },
      isLatestSubmission: () => true,
      isEmpty: composer.isEmpty,
      restore: composer.restore,
    });

    expect(composer.content).toEqual(submitted);
  });

  it("does not restore when the user has typed a new draft", async () => {
    const composer = createComposer();
    composer.clear.mockImplementation(() => {});

    await submitComposerMessage({
      submitted,
      clear: composer.clear,
      send: async () => false,
      isLatestSubmission: () => true,
      isEmpty: () => false,
      restore: composer.restore,
    });

    expect(composer.restore).not.toHaveBeenCalled();
  });

  it("does not restore a stale failure over a newer submission", async () => {
    const composer = createComposer();

    await submitComposerMessage({
      submitted,
      clear: composer.clear,
      send: async () => false,
      isLatestSubmission: () => false,
      isEmpty: composer.isEmpty,
      restore: composer.restore,
    });

    expect(composer.restore).not.toHaveBeenCalled();
  });
});
