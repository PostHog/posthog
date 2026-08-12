import { describe, expect, it, vi } from "vitest";
import { createAttachmentPreparer } from "./attachmentPreparer";
import type { CloudPromptBlock, PendingAttachment } from "./types";

function attachment(id: string): PendingAttachment {
  return {
    kind: "document",
    id,
    uri: `file://${id}.txt`,
    fileName: `${id}.txt`,
    mimeType: "text/plain",
  };
}

function block(id: string): CloudPromptBlock {
  return { type: "text", text: id };
}

describe("createAttachmentPreparer", () => {
  it("caches a resolved block and reuses it across prepares", async () => {
    const build = vi.fn(async (att: PendingAttachment) => block(att.id));
    const preparer = createAttachmentPreparer(build);

    const first = await preparer.prepare(attachment("a"));
    const second = await preparer.prepare(attachment("a"));

    expect(first).toEqual(block("a"));
    expect(second).toBe(first);
    expect(build).toHaveBeenCalledTimes(1);
  });

  it("dedupes concurrent preparation of the same attachment", async () => {
    const build = vi.fn(async (att: PendingAttachment) => block(att.id));
    const preparer = createAttachmentPreparer(build);

    const [first, second] = await Promise.all([
      preparer.prepare(attachment("a")),
      preparer.prepare(attachment("a")),
    ]);

    expect(first).toBe(second);
    expect(build).toHaveBeenCalledTimes(1);
  });

  it("prepares distinct attachments independently", async () => {
    const build = vi.fn(async (att: PendingAttachment) => block(att.id));
    const preparer = createAttachmentPreparer(build);

    expect(await preparer.prepare(attachment("a"))).toEqual(block("a"));
    expect(await preparer.prepare(attachment("b"))).toEqual(block("b"));
    expect(build).toHaveBeenCalledTimes(2);
  });

  it("evicts a failed preparation so it can be retried", async () => {
    const build = vi
      .fn<(att: PendingAttachment) => Promise<CloudPromptBlock>>()
      .mockRejectedValueOnce(new Error("too large"))
      .mockImplementation(async (att) => block(att.id));
    const preparer = createAttachmentPreparer(build);

    await expect(preparer.prepare(attachment("a"))).rejects.toThrow(
      "too large",
    );
    expect(await preparer.prepare(attachment("a"))).toEqual(block("a"));
    expect(build).toHaveBeenCalledTimes(2);
  });

  it("re-reads after forget", async () => {
    const build = vi.fn(async (att: PendingAttachment) => block(att.id));
    const preparer = createAttachmentPreparer(build);

    await preparer.prepare(attachment("a"));
    preparer.forget("a");
    await preparer.prepare(attachment("a"));

    expect(build).toHaveBeenCalledTimes(2);
  });
});
