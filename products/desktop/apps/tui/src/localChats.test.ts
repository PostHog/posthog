import { existsSync, mkdtempSync, readdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { Task } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import { LocalChats, linkLocalChats } from "./localChats";

const session = (cwd: string, firstMessage: string): string =>
  [
    { type: "session", version: 3, id: "s1", cwd },
    { type: "custom", customType: "posthog.pi.task-context", data: {} },
    {
      type: "message",
      message: {
        role: "user",
        content: [{ type: "text", text: firstMessage }],
      },
    },
    {
      type: "message",
      message: {
        role: "assistant",
        content: [{ type: "text", text: "On it" }],
      },
    },
  ]
    .map((line) => JSON.stringify(line))
    .join("\n");

describe("local chats", () => {
  it("clears a chat by moving its session file aside, and clears a chat that has no file yet", () => {
    const dir = mkdtempSync(join(tmpdir(), "tui-local-"));
    writeFileSync(join(dir, "task-1.jsonl"), session("/work/repo", "Hi"));
    const chats = new LocalChats(dir);

    chats.archive("task-1");
    chats.archive("task-2");

    expect(existsSync(chats.sessionFile("task-1"))).toBe(false);
    expect(chats.list().size).toBe(0);
    expect(readdirSync(join(dir, "cleared"))).toEqual([
      expect.stringMatching(/^task-1\.\d+\.jsonl$/),
    ]);
  });

  it("remembers which agent a chat runs, through linking and clearing", () => {
    const dir = mkdtempSync(join(tmpdir(), "tui-local-"));
    writeFileSync(join(dir, "task-1.jsonl"), session("/work/repo", "Hi"));
    const chats = new LocalChats(dir);

    expect(chats.harnessOf("task-1")).toBe("pi");
    expect(chats.harnessOf("task-9")).toBeNull();
    chats.remember("local:a", "claude");
    chats.link("local:a", "task-2");
    chats.archive("task-2");

    expect(chats.harnessOf("task-2")).toBe("claude");
    expect([...chats.list().keys()].sort()).toEqual(["task-1", "task-2"]);
  });

  it("gives each chat a task named from its first message, and keeps a chat it could not link for the next start", async () => {
    const dir = mkdtempSync(join(tmpdir(), "tui-local-"));
    writeFileSync(
      join(dir, "local:aaa.jsonl"),
      session("/work/repo", "Fix the flaky test"),
    );
    writeFileSync(join(dir, "local:bbb.jsonl"), session("/work/other", "Boom"));
    const chats = new LocalChats(dir);
    const asked: { firstMessage: string; cwd: string | null }[] = [];

    const linked = await linkLocalChats(chats, async (chat) => {
      asked.push({ firstMessage: chat.firstMessage, cwd: chat.cwd });
      if (chat.firstMessage === "Boom") throw new Error("offline");
      return { id: "task-1", title: "Fix flaky test" } as Task;
    });

    expect(asked).toEqual(
      expect.arrayContaining([
        { firstMessage: "Fix the flaky test", cwd: "/work/repo" },
        { firstMessage: "Boom", cwd: "/work/other" },
      ]),
    );
    expect([...linked.keys()]).toEqual(["local:aaa"]);
    expect([...chats.list().keys()]).toEqual(["task-1"]);
    expect(existsSync(join(dir, "local:aaa.jsonl"))).toBe(false);
    expect(chats.unlinked().map((chat) => chat.legacyId)).toEqual([
      "local:bbb",
    ]);
  });
});
