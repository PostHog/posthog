import type { PiRpcClient } from "@posthog/agent/pi/rpc-client";
import { describe, expect, it, vi } from "vitest";
import { LocalSession } from "./local";
import type { RunView } from "./runs";
import { transcriptFrom } from "./transcript";

function fakeClient() {
  const send = vi.fn(async (command: { id?: string; type: string }) => ({
    id: command.id,
    type: "response",
    command: command.type,
    success: true,
  }));
  const client = {
    onEvent: () => () => {},
    send,
    start: vi.fn(async () => {}),
    stop: vi.fn(async () => {}),
    getEntries: async () => ({
      entries: [
        {
          type: "message",
          id: "e1",
          message: {
            role: "user",
            content: [{ type: "text", text: "earlier" }],
            timestamp: 1,
          },
        },
      ],
      leafId: null,
    }),
    getCommands: async () => [
      {
        name: "skill:review",
        description: "Review a PR",
        source: "skill",
        sourceInfo: {},
      },
    ],
  };
  return { client: client as unknown as PiRpcClient, send };
}

describe("LocalSession", () => {
  it("shows the saved conversation once started", async () => {
    const { client } = fakeClient();
    const session = new LocalSession(client);
    let view: RunView | null = null;
    session.watch((next) => {
      view = next;
    });

    await session.start();

    expect(view).toMatchObject({ loaded: true, status: "in_progress" });
    expect(
      transcriptFrom("pi", (view as unknown as RunView).entries).lines,
    ).toMatchObject([{ kind: "user", text: "earlier" }]);
  });

  it("sends messages and exposes the run's commands", async () => {
    const { client, send } = fakeClient();
    const session = new LocalSession(client);
    await session.start();

    await session.prompt("Fix the flaky test");

    expect(send).toHaveBeenCalledWith(
      expect.objectContaining({
        type: "prompt",
        message: "Fix the flaky test",
      }),
    );
    expect(await session.control.commands()).toEqual([
      { name: "skill:review", description: "Review a PR" },
    ]);
  });
});
