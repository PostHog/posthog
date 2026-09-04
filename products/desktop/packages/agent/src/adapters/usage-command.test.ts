import type {
  AgentSideConnection,
  PromptRequest,
} from "@agentclientprotocol/sdk";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { handleUsageCommand, isUsageCommand } from "./usage-command";

const fetchMock = vi.fn();
vi.stubGlobal("fetch", fetchMock);

describe("usage command", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("loads billing-period credits without forwarding the command to a model", async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue({
        ai_credits: {
          exhausted: false,
          used_usd: 12.34,
          limit_usd: 20,
        },
        billing_period_end: "2026-10-01T00:00:00Z",
      }),
    });
    const sessionUpdate = vi.fn().mockResolvedValue(undefined);
    const client = { sessionUpdate } as unknown as AgentSideConnection;
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
          url: "https://gateway.example.com/v1/usage/slack_app",
          authToken: "token",
          projectId: "7",
        },
      }),
    ).resolves.toEqual({ stopReason: "end_turn" });

    expect(fetchMock).toHaveBeenCalledWith(
      "https://gateway.example.com/v1/usage/slack_app",
      {
        headers: {
          Authorization: "Bearer token",
          "X-PostHog-Project-Id": "7",
        },
      },
    );
    expect(sessionUpdate).toHaveBeenCalledTimes(2);
    expect(sessionUpdate.mock.calls[1]?.[0]).toEqual(
      expect.objectContaining({
        update: expect.objectContaining({
          sessionUpdate: "agent_message_chunk",
          content: expect.objectContaining({
            text: expect.stringContaining(
              "**Billing period**: 1,234 of 2,000 credits",
            ),
          }),
        }),
      }),
    );
  });

  it("does not claim prompts that include another visible block", () => {
    const params = {
      sessionId: "session-1",
      prompt: [
        { type: "text", text: "/usage" },
        { type: "text", text: "for this task" },
      ],
    } as PromptRequest;

    expect(isUsageCommand(params)).toBe(false);
  });
});
