import { initTheme } from "@earendil-works/pi-coding-agent";
import { stripTerminalSequences } from "@earendil-works/pi-tui";
import { beforeAll, describe, expect, it } from "vitest";
import { ChatView } from "./chatView";
import type { TranscriptLine } from "./transcript";

const plain = (lines: string[]): string[] =>
  lines.map((line) => stripTerminalSequences(line).trimEnd());

const replies = (count: number): TranscriptLine[] =>
  Array.from({ length: count }, (_, index) => ({
    kind: "assistant" as const,
    id: `a${index}`,
    text: `Reply ${index}`,
  }));

describe("ChatView", () => {
  beforeAll(() => initTheme("dark"));

  it("renders messages with pi's components, without shell-integration markers", () => {
    const chat = new ChatView();
    chat.setTranscript([
      { kind: "user", id: "u1", text: "Rename the helper" },
      { kind: "assistant", id: "a1", text: "On **it**." },
      { kind: "tool", id: "t1", title: "Edit src/a.ts", status: "completed" },
    ]);
    const lines = chat.render(40, 20);

    expect(lines.join("\n")).not.toContain("\x1b]133");
    const text = plain(lines).join("\n");
    expect(text).toContain("Rename the helper");
    expect(text).toContain("On it.");
    expect(text).toContain("Edit src/a.ts");
    expect(lines).toHaveLength(20);
  });

  it("follows new messages, and holds position once scrolled up", () => {
    const chat = new ChatView();
    chat.setTranscript(replies(30));
    expect(plain(chat.render(40, 5)).join("\n")).toContain("Reply 29");

    chat.scrollBy(-20);
    const held = plain(chat.render(40, 5));
    chat.setTranscript(replies(31));
    expect(plain(chat.render(40, 5))).toEqual(held);

    chat.scrollToEnd();
    expect(plain(chat.render(40, 5)).join("\n")).toContain("Reply 30");
  });

  it("marks the top while earlier messages exist, and keeps the reader's place when they arrive", () => {
    const chat = new ChatView();
    chat.setTranscript(replies(30).slice(20), { hasOlder: true });
    chat.render(40, 5);
    chat.scrollBy(-1000);
    expect(chat.isAtTop()).toBe(true);
    expect(plain(chat.render(40, 5))[0]).toContain("Loading earlier messages");

    chat.scrollBy(2);
    const reading = plain(chat.render(40, 5));
    chat.setTranscript(replies(30), { hasOlder: false });
    expect(plain(chat.render(40, 5))).toEqual(reading);
  });

  it("keeps messages tight and puts one blank line between user, tool and agent blocks", () => {
    const chat = new ChatView();
    chat.setTranscript([
      { kind: "user", id: "u1", text: "yo" },
      { kind: "tool", id: "t1", title: "Read file", status: "completed" },
      { kind: "tool", id: "t2", title: "Edit file", status: "completed" },
      { kind: "assistant", id: "a1", text: "Done." },
      { kind: "user", id: "u2", text: "thanks!" },
    ]);
    const lines = plain(chat.render(40, 8)).map((line) => line.trim());

    expect(lines).toEqual([
      "yo",
      "",
      "● Read file",
      "● Edit file",
      "",
      "Done.",
      "",
      "thanks!",
    ]);
    // Ink draws an empty string with no height, so a blank line must carry a space to take up a row.
    expect(chat.render(40, 8).every((line) => line.length > 0)).toBe(true);
  });
});
