import { initTheme } from "@earendil-works/pi-coding-agent";
import { stripTerminalSequences } from "@earendil-works/pi-tui";
import { beforeAll, describe, expect, it } from "vitest";
import { ChatView, overlayBottom } from "./chatView";
import type { TranscriptLine } from "./transcript";

const plain = (lines: string[]): string[] =>
  lines.map((line) => stripTerminalSequences(line).trimEnd());

const tool = (
  id: string,
  title: string,
  status = "completed",
  detail = "cmd",
  output = "",
): TranscriptLine => ({ kind: "tool", id, title, status, detail, output });

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
      tool("t1", "edit"),
    ]);
    const lines = chat.render(40, 20);

    expect(lines.join("\n")).not.toContain("\x1b]133");
    const text = plain(lines).join("\n");
    expect(text).toContain("Rename the helper");
    expect(text).toContain("On it.");
    expect(text).toContain("Edited 1 file");
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
      tool("t1", "read"),
      tool("t2", "edit"),
      { kind: "assistant", id: "a1", text: "Done." },
      { kind: "user", id: "u2", text: "thanks!" },
    ]);
    const lines = plain(chat.render(40, 7)).map((line) => line.trim());

    expect(lines).toEqual([
      "yo",
      "",
      "▸ Read 1 file · edited 1 file",
      "",
      "Done.",
      "",
      "thanks!",
    ]);
    // Ink draws an empty string with no height, so a blank line must carry a space to take up a row.
    expect(chat.render(40, 8).every((line) => line.length > 0)).toBe(true);
  });

  it("opens a tool group on a click to show each call and its output", () => {
    const chat = new ChatView();
    chat.setTranscript([
      { kind: "user", id: "u1", text: "yo" },
      tool("t1", "bash", "failed", "ls src", "a.ts\nb.ts"),
      tool("t2", "bash"),
    ]);
    const closed = plain(chat.render(40, 3)).map((line) => line.trim());
    expect(closed[2]).toBe("▸ Ran 2 shell commands · 1 failed");

    expect(chat.hoverAt(2)).toBe(true);
    expect(chat.hoverAt(2)).toBe(false);
    expect(chat.render(40, 3)[2]).not.toContain("\u001b[2m▸");
    expect(chat.hoverAt(null)).toBe(true);
    expect(chat.toggleAt(0)).toBe(false);
    expect(chat.toggleAt(2)).toBe(true);
    expect(plain(chat.render(40, 8)).map((line) => line.trim())).toEqual([
      "yo",
      "",
      "▾ Ran 2 shell commands · 1 failed",
      "● bash ls src",
      "⎿ a.ts",
      "b.ts",
      "● bash cmd",
      "",
    ]);
  });

  it("shows the run's status right under the latest message", () => {
    const chat = new ChatView();
    chat.setTranscript([{ kind: "user", id: "u1", text: "yo" }], {
      notice: { text: "Thinking…", tone: "working" },
    });
    const lines = plain(chat.render(40, 4)).map((line) => line.trim());

    expect(lines[0]).toBe("yo");
    expect(lines[1]).toBe("");
    expect(lines[2]).toMatch(/Thinking…$/);
  });
});

describe("overlayBottom", () => {
  it.each([
    [
      "covers the last rows",
      ["a", "b", "c", "d"],
      ["x", "y"],
      ["a", "b", "x", "y"],
    ],
    ["keeps the chat when nothing floats", ["a", "b"], [], ["a", "b"]],
    [
      "shows the popup's end when it is taller than the chat",
      ["a", "b"],
      ["x", "y", "z"],
      ["y", "z"],
    ],
  ])("%s", (_, lines, popup, expected) => {
    expect(overlayBottom(lines, popup)).toEqual(expected);
  });
});
