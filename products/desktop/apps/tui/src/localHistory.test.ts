import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it, vi } from "vitest";
import type { LocalAgent } from "./local";
import { LocalChats } from "./localChats";
import { LocalChatHandle, localHistory } from "./localHistory";
import { emptyRunView, type RunView } from "./runs";
import { transcriptFrom } from "./transcript";

const line = (entry: object): string => `${JSON.stringify(entry)}\n`;
const start = (): Promise<never> =>
  Promise.reject(new Error("not started in this test"));

describe("LocalChatHandle", () => {
  it("shows the saved conversation, then the agent the first message starts, through the same watch", async () => {
    const viewsFromAgent: Array<(view: RunView) => void> = [];
    const agent = {
      watch: (onView: (view: RunView) => void) => {
        viewsFromAgent.push(onView);
        onView({ ...emptyRunView, loaded: true, entries: [{ type: "live" }] });
        return () => viewsFromAgent.splice(viewsFromAgent.indexOf(onView), 1);
      },
      watchPrompts: () => () => {},
      prompt: vi.fn(async () => {}),
      control: {
        models: async () => ({
          available: [],
          current: { provider: "posthog", id: "m", name: "M" },
          effort: null,
        }),
      },
    } as unknown as LocalAgent;
    const handle = new LocalChatHandle(
      {
        runtime: "pi",
        plan: false,
        model: undefined,
        view: { ...emptyRunView, loaded: true, entries: [{ type: "saved" }] },
      },
      async () => agent,
    );
    const seen: RunView[] = [];
    const stop = handle.watch((view) => seen.push(view));
    expect(seen.at(-1)?.entries).toEqual([{ type: "saved" }]);
    expect((await handle.control.models()).current).toBeNull();

    await handle.prompt("hi");

    expect(agent.prompt).toHaveBeenCalledWith("hi", undefined);
    expect(seen.at(-1)?.entries).toEqual([{ type: "live" }]);
    expect((await handle.control.models()).current?.id).toBe("m");
    stop();
    expect(viewsFromAgent).toHaveLength(0);
  });
});

describe("localHistory", () => {
  it("reads a pi chat's saved conversation from its session file without an agent", async () => {
    const dir = mkdtempSync(join(tmpdir(), "local-history-"));
    writeFileSync(
      join(dir, "t1.jsonl"),
      line({
        type: "session",
        version: 3,
        id: "s1",
        timestamp: "2026-10-09T09:04:45.006Z",
        cwd: dir,
      }) +
        line({
          type: "model_change",
          id: "c1",
          parentId: null,
          timestamp: "2026-10-09T09:04:45.500Z",
          provider: "openai-codex",
          modelId: "gpt-6",
        }) +
        line({
          type: "message",
          id: "m1",
          parentId: "c1",
          timestamp: "2026-10-09T09:04:46.000Z",
          message: {
            role: "user",
            content: [{ type: "text", text: "earlier" }],
            timestamp: 1,
          },
        }),
    );

    const cold = await localHistory(new LocalChats(dir), "t1", start);
    let view: RunView | null = null;
    cold?.watch((next) => {
      view = next;
    });

    expect(cold).toMatchObject({ runtime: "pi", plan: true, model: "gpt-6" });
    expect(view).toMatchObject({ loaded: true, local: true });
    expect(
      transcriptFrom("pi", (view as unknown as RunView).entries).lines,
    ).toMatchObject([{ kind: "user", text: "earlier" }]);
    expect(await localHistory(new LocalChats(dir), "t2", start)).toBeNull();
  });

  it("reads a Claude chat's saved log", async () => {
    const dir = mkdtempSync(join(tmpdir(), "local-history-"));
    const chats = new LocalChats(dir);
    chats.remember("c1", "claude");
    chats.acpLog("c1").append({
      type: "acp_message",
      timestamp: "2026-10-09T09:04:46.000Z",
    } as never);

    const cold = await localHistory(chats, "c1", start);
    let view: RunView | null = null;
    cold?.watch((next) => {
      view = next;
    });

    expect(cold).toMatchObject({ runtime: "acp", plan: true });
    expect(view).toMatchObject({ loaded: true, local: true });
    expect((view as unknown as RunView).entries).toHaveLength(1);
  });
});
