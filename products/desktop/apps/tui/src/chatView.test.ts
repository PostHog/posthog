import { readFileSync } from "node:fs";
import { initTheme } from "@earendil-works/pi-coding-agent";
import {
  resetCapabilitiesCache,
  setCapabilities,
  stripTerminalSequences,
} from "@earendil-works/pi-tui";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { ChatView, overlayBottom, shimmer } from "./chatView";
import { IMAGES_DIR } from "./images";
import { blue } from "./theme";
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

  it("offers a way back to the latest message only while scrolled up", () => {
    const chat = new ChatView();
    chat.setTranscript(replies(30));
    expect(plain(chat.render(40, 5)).join("\n")).not.toContain(
      "Jump to bottom",
    );

    chat.scrollBy(-20);
    const scrolled = plain(chat.render(40, 5));
    const column = scrolled[4].indexOf("Jump to bottom");
    expect(column).toBeGreaterThan(0);
    expect(chat.jumpAt(3, column)).toBe(false);
    expect(chat.jumpAt(4, column)).toBe(true);

    const latest = plain(chat.render(40, 5)).join("\n");
    expect(latest).toContain("Reply 29");
    expect(latest).not.toContain("Jump to bottom");
  });

  it.each([
    ["below the status while the agent has not read it", true, 1],
    ["in the conversation once the agent has it", false, -1],
  ])("shows a message sent mid-turn %s", (_, queued, order) => {
    const chat = new ChatView();
    chat.setTranscript(
      [
        { kind: "user", id: "u1", text: "Run the QA" },
        { kind: "assistant", id: "a1", text: "On it." },
        { kind: "user", id: "pending", text: "you good?" },
      ],
      { notice: { text: "Running", tone: "working" }, queued },
    );
    const text = plain(chat.render(60, 20));
    const status = text.findIndex((line) => line.includes("Running"));
    const message = text.findIndex((line) => line.includes("you good?"));

    expect(Math.sign(message - status)).toBe(order);
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
      "❯ yo",
      "",
      "▶ Read 1 file · edited 1 file",
      "",
      "Done.",
      "",
      "❯ thanks!",
    ]);
    // Ink draws an empty string with no height, so a blank line must carry a space to take up a row.
    expect(chat.render(40, 8).every((line) => line.length > 0)).toBe(true);
  });

  it("lists a message's images under it, each opening the saved file", () => {
    const chat = new ChatView();
    chat.setTranscript([
      {
        kind: "user",
        id: "u1",
        text: "compare [Image #2] with [Image #3]",
        images: [
          {
            data: Buffer.from("first").toString("base64"),
            mimeType: "image/png",
          },
          {
            data: Buffer.from("second").toString("base64"),
            mimeType: "image/jpeg",
          },
        ],
      },
    ]);
    const rows = plain(chat.render(40, 4));
    const first = rows.findIndex(
      (row) => row.includes("[Image #2]") && row.includes("└"),
    );

    expect(rows.slice(first, first + 2).map((row) => row.trim())).toEqual([
      "└ [Image #2]",
      "└ [Image #3]",
    ]);
    const files = [chat.imageAt(first), chat.imageAt(first + 1)];
    expect(files.every((file) => file?.startsWith(IMAGES_DIR))).toBe(true);
    expect(files.map((file) => readFileSync(file ?? "", "utf8"))).toEqual([
      "first",
      "second",
    ]);
    expect(chat.imageAt(0)).toBeNull();
  });

  it("shows an assistant's code block as indented code, without its fences or language", () => {
    const chat = new ChatView();
    chat.setTranscript([
      {
        kind: "assistant",
        id: "a",
        text: "Before.\n\n```rust\nfn main() {}\n```\n\nAfter.",
      },
    ]);

    expect(plain(chat.render(30, 5))).toEqual([
      " Before.",
      "",
      "   fn main() {}",
      "",
      " After.",
    ]);
  });

  it("colours inline code and links PostHog blue", () => {
    const chat = new ChatView();
    chat.setTranscript([
      {
        kind: "assistant",
        id: "a",
        text: "Run `pnpm test` and read [the docs](https://posthog.com/docs).",
      },
    ]);
    const row = chat.render(70, 1)[0];

    expect(row).toContain(blue("pnpm test"));
    expect(row).toContain(blue("the docs"));
  });

  it("cuts a long command short so the status keeps its time and tool count, faint", () => {
    const chat = new ChatView();
    chat.setTranscript(
      [
        { kind: "user", id: "u1", text: "yo" },
        tool("t1", "bash", "in_progress", "pnpm test"),
      ],
      {
        notice: {
          text: "Running",
          subject: `cd ${"/very/long/path".repeat(6)} && pnpm test`,
          detail: "2m 4s · 3 tools",
          tone: "working",
        },
      },
    );
    const row = chat.render(50, 3)[2];
    const before = row.slice(0, row.indexOf("2m 4s"));
    const faint = [
      ...before.matchAll(new RegExp(`${"\u001b"}\\[(0|2|22)?m`, "g")),
    ];

    expect(stripTerminalSequences(row).trimEnd()).toMatch(
      /…\s·\s2m 4s · 3 tools$/,
    );
    expect(faint.at(-1)?.[1]).toBe("2");
  });

  it("opens a tool group on a click to show each call and its output", () => {
    const chat = new ChatView();
    chat.setTranscript([
      { kind: "user", id: "u1", text: "yo" },
      tool("t1", "bash", "failed", "ls src", "a.ts\nb.ts"),
      tool("t2", "bash"),
    ]);
    const closed = plain(chat.render(40, 3)).map((line) => line.trim());
    expect(closed[2]).toBe("▶ Ran 2 shell commands · 1 failed");

    expect(chat.hoverAt(2)).toBe(true);
    expect(chat.hoverAt(2)).toBe(false);
    expect(chat.render(40, 3)[2]).not.toContain("\u001b[2m▶");
    expect(chat.hoverAt(null)).toBe(true);
    expect(chat.toggleAt(0)).toBe(false);
    expect(chat.toggleAt(2)).toBe(true);
    expect(plain(chat.render(40, 8)).map((line) => line.trim())).toEqual([
      "❯ yo",
      "",
      "▼ Ran 2 shell commands · 1 failed",
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

  describe("selecting text", () => {
    const INVERSE = new RegExp(`${"\u001b"}\\[7m(.*?)${"\u001b"}\\[27m`, "g");
    const highlighted = (lines: string[]): string[] =>
      lines.flatMap((line) =>
        [...line.matchAll(INVERSE)].map((match) =>
          stripTerminalSequences(match[1]),
        ),
      );
    const chatWith = (): { chat: ChatView; lines: string[] } => {
      const chat = new ChatView();
      chat.setTranscript([
        ...replies(6),
        { kind: "assistant", id: "a", text: "alpha beta gamma" },
        { kind: "user", id: "u", text: "delta epsilon" },
      ]);
      return { chat, lines: chat.render(40, 5) };
    };
    const cellOf = (lines: string[], text: string) => {
      const row = plain(lines).findIndex((line) => line.includes(text));
      return { row, column: plain(lines)[row].indexOf(text) };
    };

    it.each([
      ["forwards", false],
      ["backwards", true],
    ])("copies the text drawn between two cells, dragged %s", (_, reverse) => {
      const { chat, lines } = chatWith();
      const beta = cellOf(lines, "beta");
      const epsilon = cellOf(lines, "epsilon");
      const from = beta;
      const to = { row: epsilon.row, column: epsilon.column + 2 };
      if (reverse) chat.select(to, from);
      else chat.select(from, to);

      expect(chat.selectedText()).toBe("beta gamma\n\ndelta eps");
      // The highlight covers what is drawn, caret included; the copy above leaves it out.
      expect(highlighted(chat.render(40, 5))).toEqual([
        "beta gamma",
        " ❯ delta eps",
      ]);
      expect(plain(chat.render(40, 5))).toEqual(plain(lines));
    });

    it.each([
      ["after", "x.mjs", " in", false],
      ["inside", "node", "x.mjs", true],
    ])(
      "gives text %s a selected code span the colour it had before",
      (_, selected, probe, coloured) => {
        const chat = new ChatView();
        chat.setTranscript([
          { kind: "assistant", id: "a", text: "Run `node x.mjs` in Ghostty" },
        ]);
        const lines = chat.render(40, 3);
        const from = cellOf(lines, "node");
        const to = cellOf(lines, selected);
        chat.select(from, {
          row: to.row,
          column: to.column + selected.length - 1,
        });
        const row = chat.render(40, 3)[from.row];
        // The colour in force where the probe text starts: set by 38, ended by 39 or a full reset.
        const before = row.slice(0, row.lastIndexOf(probe));
        const codes = [
          ...before.matchAll(
            new RegExp(`${"\u001b"}\\[(38[;:][^m]*|39|0)m`, "g"),
          ),
        ];
        expect(codes.at(-1)?.[1].startsWith("38") ?? false).toBe(coloured);
      },
    );

    it("copies wrapped rows as one line each, keeping paragraph and list breaks", () => {
      const paragraph =
        "A small helper cuts the row at a column and keeps every styling code in place.";
      const item = "a list item long enough to wrap onto the next row";
      const chat = new ChatView();
      chat.setTranscript([
        {
          kind: "assistant",
          id: "a",
          text: `${paragraph}\n\n- ${item}\n- short item\n\n\`\`\`\nconst x = 1;\nconst y = 2;\n\`\`\``,
        },
      ]);
      const lines = chat.render(40, 20);
      chat.select({ row: 0, column: 0 }, { row: 19, column: 39 });

      expect(lines.filter((line) => line.trim()).length).toBeGreaterThan(6);
      expect(chat.selectedText().trimEnd()).toBe(
        [
          paragraph,
          "",
          `- ${item}`,
          "- short item",
          "",
          "  const x = 1;",
          "  const y = 2;",
        ].join("\n"),
      );
    });

    it("keeps the selection on the same text when the chat scrolls", () => {
      const { chat, lines } = chatWith();
      const gamma = cellOf(lines, "gamma");
      chat.select(gamma, { row: gamma.row, column: gamma.column + 4 });
      chat.scrollBy(-2);

      expect(chat.selectedText()).toBe("gamma");
      // A row taller, so the way back to the latest message does not cover it.
      expect(highlighted(chat.render(40, 6))).toEqual(["gamma"]);
    });

    it("keeps a drag past the chat's edges inside the chat", () => {
      const { chat, lines } = chatWith();
      const delta = cellOf(lines, "delta");
      chat.select(delta, { row: 99, column: 99 });

      expect(chat.selectedText()).toBe("delta epsilon");
    });

    it("clears the highlight and the text", () => {
      const { chat, lines } = chatWith();
      chat.select(cellOf(lines, "alpha"), cellOf(lines, "beta"));
      chat.clearSelection();

      expect(chat.selectedText()).toBe("");
      expect(highlighted(chat.render(40, 5))).toEqual([]);
    });
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
      "▶ Ran 1 shell command",
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

    expect(lines[0]).toBe("❯ yo");
    expect(lines[1]).toBe("");
    expect(lines[2]).toMatch(/Thinking…$/);
  });

  it("folds an open turn's latest tool calls into the status line, which a click opens", () => {
    const chat = new ChatView();
    chat.setTranscript(
      [
        { kind: "user", id: "u1", text: "yo" },
        tool("t1", "bash"),
        tool("t2", "bash", "in_progress", "pnpm test"),
      ],
      {
        notice: {
          text: "Running",
          detail: "pnpm test · 30s · 2 tools",
          tone: "working",
        },
      },
    );
    const trimmed = (height: number): string[] =>
      plain(chat.render(60, height)).map((line) => line.trim());

    expect(trimmed(4)).toEqual([
      "❯ yo",
      "",
      "▶ Running pnpm test · 30s · 2 tools",
      "",
    ]);
    expect(chat.toggleAt(2)).toBe(true);
    expect(trimmed(5).slice(2)).toEqual([
      "▼ Running pnpm test · 30s · 2 tools",
      "● bash cmd",
      "● bash pnpm test",
    ]);
    // The running call's dot pulses; the finished one holds still.
    const frameAt = (now: number): string[] => {
      const clock = vi.spyOn(Date, "now").mockReturnValue(now);
      const rows = chat.render(60, 5).slice(3, 5);
      clock.mockRestore();
      return rows;
    };
    const [done, running] = frameAt(0);
    const [doneLater, runningLater] = frameAt(500);
    expect(doneLater).toBe(done);
    expect(runningLater).not.toBe(running);
  });
});

describe("shimmer", () => {
  it("sweeps a highlight along the text without changing what it says", () => {
    const frames = [0, 80, 160].map((now) => shimmer("Running", now));

    expect(new Set(frames).size).toBe(3);
    // Bold shares faint's end code, so in a faint pane it turned the text after it bright.
    expect(frames.some((frame) => frame.includes("\u001b[1m"))).toBe(false);
    expect(frames.map((frame) => stripTerminalSequences(frame))).toEqual([
      "Running",
      "Running",
      "Running",
    ]);
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
