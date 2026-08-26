import { describe, expect, it } from "vitest";
import { getRemotePiConversation } from "./remote-rpc-client";

describe("getRemotePiConversation", () => {
  it("renders persisted custom messages, ending the turn on a terminal flow entry", async () => {
    const entries = [
      {
        type: "custom_message",
        id: "entry-1",
        parentId: null,
        timestamp: "2026-08-26T13:00:00.000Z",
        customType: "posthog-agent-flow",
        content: "**Plan and build** flow started.",
        display: true,
        details: {
          flowId: "f1",
          flowName: "Plan and build",
          status: "running",
        },
      },
      {
        type: "custom_message",
        id: "entry-2",
        parentId: "entry-1",
        timestamp: "2026-08-26T13:00:01.000Z",
        customType: "other-extension",
        content: "hidden bookkeeping",
        display: false,
      },
      {
        type: "custom_message",
        id: "entry-3",
        parentId: "entry-2",
        timestamp: "2026-08-26T13:05:00.000Z",
        customType: "posthog-agent-flow",
        content: "**Plan and build** finished.",
        display: true,
        details: {
          flowId: "f1",
          flowName: "Plan and build",
          status: "completed",
        },
      },
    ];
    const client = {
      getEntries: async () => ({ entries }) as never,
    };

    const events = await getRemotePiConversation(client);

    const texts = events.flatMap((event) =>
      event.type === "assistant_message_chunk" && event.content.type === "text"
        ? [event.content.text]
        : [],
    );
    expect(texts).toEqual([
      "**Plan and build** flow started.",
      "**Plan and build** finished.",
    ]);
    expect(events.at(-1)).toMatchObject({
      type: "turn_completed",
      stopReason: "stop",
    });
  });
});
