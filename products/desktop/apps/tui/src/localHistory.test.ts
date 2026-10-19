import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { LocalChats } from "./localChats";
import { localHistory } from "./localHistory";
import { transcriptFrom } from "./transcript";

const line = (entry: object): string => `${JSON.stringify(entry)}\n`;

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
          type: "message",
          id: "m1",
          parentId: null,
          timestamp: "2026-10-09T09:04:46.000Z",
          message: {
            role: "user",
            content: [{ type: "text", text: "earlier" }],
            timestamp: 1,
          },
        }),
    );

    const view = await localHistory(new LocalChats(dir), "t1");

    expect(view).toMatchObject({ loaded: true, local: true });
    expect(transcriptFrom("pi", view?.entries ?? []).lines).toMatchObject([
      { kind: "user", text: "earlier" },
    ]);
    expect(await localHistory(new LocalChats(dir), "t2")).toBeNull();
  });

  it("reads a Claude chat's saved log", async () => {
    const dir = mkdtempSync(join(tmpdir(), "local-history-"));
    const chats = new LocalChats(dir);
    chats.remember("c1", "claude");
    chats.acpLog("c1").append({
      type: "acp_message",
      timestamp: "2026-10-09T09:04:46.000Z",
    } as never);

    const view = await localHistory(chats, "c1");

    expect(view).toMatchObject({ loaded: true, local: true });
    expect(view?.entries).toHaveLength(1);
  });
});
