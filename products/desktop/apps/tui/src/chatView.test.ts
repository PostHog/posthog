import { initTheme } from "@earendil-works/pi-coding-agent";
import {
  resetCapabilitiesCache,
  setCapabilities,
  stripTerminalSequences,
} from "@earendil-works/pi-tui";
import { afterEach, beforeAll, describe, expect, it } from "vitest";
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

  describe.each([
    ["supports hyperlinks", true],
    ["prints link addresses", false],
  ])("links, when the terminal %s", (_, hyperlinks) => {
    afterEach(() => resetCapabilitiesCache());
    const pr = "https://github.com/PostHog/posthog/pull/1";
    // Finds a cell on screen by the text drawn there.
    const cellOf = (
      lines: string[],
      text: string,
    ): { row: number; column: number } => {
      const row = plain(lines).findIndex((line) => line.includes(text));
      return { row, column: plain(lines)[row].indexOf(text) };
    };

    it("finds the link under a cell of the visible, scrolled chat", () => {
      setCapabilities({ images: null, trueColor: true, hyperlinks });
      const chat = new ChatView();
      chat.setTranscript([
        ...replies(10),
        { kind: "assistant", id: "link", text: `Opened ${pr}` },
      ]);
      const lines = chat.render(60, 5);

      const start = cellOf(lines, "https://github");
      expect(chat.linkAt(start.row, start.column + 2)).toBe(pr);
      const opened = cellOf(lines, "Opened");
      expect(chat.linkAt(opened.row, opened.column)).toBeNull();
      expect(chat.linkAt(99, 0)).toBeNull();
    });
  });

  it("opens the whole address from any row of a hyperlink that wraps", () => {
    setCapabilities({ images: null, trueColor: true, hyperlinks: true });
    const chat = new ChatView();
    const pr = "https://github.com/PostHog/posthog/pull/123456789/files";
    chat.setTranscript([{ kind: "assistant", id: "a1", text: pr }]);
    const lines = chat.render(30, 3);
    resetCapabilitiesCache();

    const rows = plain(lines).flatMap((line, row) =>
      line.trim() ? [row] : [],
    );
    expect(rows.length).toBeGreaterThan(1);
    for (const row of rows) expect(chat.linkAt(row, 2)).toBe(pr);
  });

  it("shows a shell command the user ran with its output, apart from the agent's tools", () => {
    const chat = new ChatView();
    chat.setTranscript([
      tool("t1", "bash"),
      {
        kind: "shell",
        id: "s1",
        command: "ls src",
        status: "completed",
        output: "1\n2\n3\n4\n5\n6\n7",
      },
    ]);
    const lines = plain(chat.render(40, 10)).map((line) => line.trim());

    expect(lines).toEqual([
      "▸ Ran 1 shell command",
      "",
      "! ls src",
      "⎿ 1",
      "2",
      "3",
      "4",
      "5",
      "… +2 lines",
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
