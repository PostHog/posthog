import { describe, expect, it } from "vitest";
import {
  buildPendingPromptKey,
  capPendingPrompts,
  listPendingPromptsNewestFirst,
  pendingPromptRecordFromContent,
  pendingPromptToContent,
} from "./pendingPrompts";

describe("pending prompts", () => {
  it("keeps the newest prompts up to the limit", () => {
    expect(
      capPendingPrompts(
        {
          old: { createdAt: 1 },
          middle: { createdAt: 2 },
          newest: { createdAt: 3 },
        },
        2,
      ),
    ).toEqual({ middle: { createdAt: 2 }, newest: { createdAt: 3 } });
  });

  it("orders prompts newest first", () => {
    const prompts = { old: { createdAt: 1 }, new: { createdAt: 2 } };
    expect(
      listPendingPromptsNewestFirst(prompts).map(({ key }) => key),
    ).toEqual(["new", "old"]);
  });

  it.each([
    ["uuid", 1, "abc", "uuid"],
    [null, 123, "abc", "pending-123-abc"],
  ])("builds a portable pending key", (uuid, timestamp, entropy, expected) => {
    expect(buildPendingPromptKey(uuid, timestamp, entropy)).toBe(expected);
  });
});

describe("pendingPromptToContent", () => {
  it("restores file chips from serialized content so attachments survive recovery", () => {
    const content = pendingPromptToContent({
      contentXml: 'fix <file path="src/a.ts" />',
      promptText: "fix @a.ts",
    });
    expect(content.segments).toContainEqual({
      type: "chip",
      chip: { type: "file", id: "src/a.ts", label: "src/a.ts" },
    });
  });

  it("falls back to plain text for records saved before content was captured", () => {
    const content = pendingPromptToContent({ promptText: "just text" });
    expect(content).toEqual({
      segments: [{ type: "text", text: "just text" }],
    });
  });
});

describe("pendingPromptRecordFromContent", () => {
  it("captures plain text, serialized chips, and attachments from the typed content", () => {
    const record = pendingPromptRecordFromContent({
      segments: [
        { type: "text", text: "fix " },
        {
          type: "chip",
          chip: { type: "file", id: "src/a.ts", label: "src/a.ts" },
        },
      ],
      attachments: [{ id: "notes.txt", label: "notes.txt" }],
    });

    expect(record.promptText).toBe("fix @src/a.ts");
    expect(record.contentXml).toContain('<file path="src/a.ts" />');
    expect(record.attachments).toEqual([
      { id: "notes.txt", label: "notes.txt" },
    ]);
  });
});
