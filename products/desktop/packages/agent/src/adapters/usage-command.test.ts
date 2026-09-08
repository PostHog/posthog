import type {
  AgentSideConnection,
  PromptRequest,
} from "@agentclientprotocol/sdk";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { handleUsageCommand, isUsageCommand } from "./usage-command";

describe("usage command", () => {
  const sessionUpdate = vi.fn().mockResolvedValue(undefined);
  const client = { sessionUpdate } as unknown as AgentSideConnection;

  beforeEach(() => {
    vi.clearAllMocks();
  });

  function promptOf(...texts: string[]): PromptRequest {
    return {
      sessionId: "session-1",
      prompt: texts.map((text) => ({ type: "text", text })),
    } as PromptRequest;
  }

  it("answers with the report instead of sending the prompt to a model", async () => {
    const params = {
      sessionId: "session-1",
      prompt: [
        {
          type: "text",
          text: "resume context",
          _meta: { ui: { hidden: true } },
        },
        { type: "text", text: " /usage " },
      ],
    } as PromptRequest;

    expect(isUsageCommand(params)).toBe(true);
    await expect(
      handleUsageCommand({
        client,
        sessionId: "session-1",
        params,
        config: {
          loadUsageMessage: () =>
            Promise.resolve(
              "## PostHog AI usage\n\n**Current conversation**: 12 credits",
            ),
        },
      }),
    ).resolves.toEqual({ stopReason: "end_turn" });

    expect(sessionUpdate).toHaveBeenCalledTimes(2);
    expect(sessionUpdate.mock.calls[1]?.[0]).toEqual(
      expect.objectContaining({
        update: expect.objectContaining({
          sessionUpdate: "agent_message_chunk",
          content: expect.objectContaining({
            text: expect.stringContaining(
              "**Current conversation**: 12 credits",
            ),
          }),
        }),
      }),
    );
  });

  it("keeps the session alive when the report cannot be loaded", async () => {
    await expect(
      handleUsageCommand({
        client,
        sessionId: "session-1",
        params: promptOf("/usage"),
        config: {
          loadUsageMessage: () => Promise.reject(new Error("gateway down")),
        },
      }),
    ).resolves.toEqual({ stopReason: "end_turn" });

    expect(sessionUpdate.mock.calls.at(-1)?.[0]).toEqual(
      expect.objectContaining({
        update: expect.objectContaining({
          content: expect.objectContaining({
            text: "Couldn't load PostHog AI usage. Try again in a moment.",
          }),
        }),
      }),
    );
  });

  it("does not claim prompts that include another visible block", () => {
    expect(isUsageCommand(promptOf("/usage", "for this task"))).toBe(false);
  });
});
