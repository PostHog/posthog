import type { AcpMessage } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import { latestAgentMessage, persistedTurnMessage } from "./latestTurnMessage";

function update(sessionUpdate: string, text?: string): AcpMessage {
  return {
    type: "acp_message",
    ts: 0,
    message: {
      method: "session/update",
      params: {
        update: {
          sessionUpdate,
          content: text === undefined ? undefined : { type: "text", text },
        },
      },
    },
  };
}

function agent(text: string): AcpMessage {
  return update("agent_message_chunk", text);
}

describe("latestTurnMessage", () => {
  it("joins the chunks the last message streamed in as", () => {
    expect(
      latestAgentMessage([
        agent("Ignore "),
        update("tool_call"),
        agent("Renamed "),
        agent("the column."),
      ]),
    ).toBe("Renamed the column.");
  });

  it.each([
    ["nothing at all", []],
    ["a run with no agent prose", [update("tool_call"), update("plan")]],
    ["prose that is only whitespace", [agent("  \n ")]],
  ])("says nothing about %s", (_case, events: AcpMessage[]) => {
    expect(latestAgentMessage(events)).toBeNull();
  });

  it("reads past a user turn to the message before it, not into it", () => {
    expect(
      latestAgentMessage([
        agent("First answer."),
        update("user_message_chunk", "and now this"),
      ]),
    ).toBe("First answer.");
  });

  // A streaming session holds tens of thousands of events and this runs while
  // the card is open, so the scan is bounded rather than proportional.
  it("gives up rather than walking an entire transcript", () => {
    const stale = agent("Said this a long time ago.");
    const filler = Array.from({ length: 600 }, () => update("tool_call"));

    expect(latestAgentMessage([stale, ...filler])).toBeNull();
  });

  it("collapses a long message onto one line and cuts it on a word", () => {
    const message = latestAgentMessage([
      agent(`Rewrote\n the importer.\n${"word ".repeat(120)}`),
    ]);

    expect(message?.startsWith("Rewrote the importer. word")).toBe(true);
    expect(message?.endsWith("…")).toBe(true);
    expect(message).not.toContain("\n");
    expect(message?.length).toBeLessThanOrEqual(241);
  });

  it.each([
    [
      "the run's closing prose",
      { final_message: "Opened the PR." },
      "Opened the PR.",
    ],
    [
      "a run that wrote nothing",
      { pr_url: "https://example.com/pull/1" },
      null,
    ],
    ["a non-string value", { final_message: 42 }, null],
    ["no output at all", null, null],
  ])("takes %s off the run", (_case, output, expected) => {
    expect(persistedTurnMessage(output as Record<string, unknown> | null)).toBe(
      expected,
    );
  });
});
