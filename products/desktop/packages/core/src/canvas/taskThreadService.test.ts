import type { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import type { TaskThreadMessage } from "@posthog/shared/domain-types";
import { describe, expect, it, vi } from "vitest";
import { TaskThreadService } from "./taskThreadService";

function message(
  overrides: Partial<TaskThreadMessage> = {},
): TaskThreadMessage {
  return {
    id: "message-id",
    task: "task-id",
    content: "@agent investigate this",
    created_at: "2026-07-16T00:00:00Z",
    ...overrides,
  };
}

function client(overrides: Partial<PostHogAPIClient> = {}): PostHogAPIClient {
  return overrides as PostHogAPIClient;
}

describe("TaskThreadService", () => {
  it("creates a message before forwarding it to the agent", async () => {
    const createTaskThreadMessage = vi.fn().mockResolvedValue(message());
    const sendTaskThreadMessageToAgent = vi
      .fn()
      .mockResolvedValue(
        message({ forwarded_to_agent_at: "2026-07-16T00:00:01Z" }),
      );
    const service = new TaskThreadService();

    await service.postMessageToAgent(
      client({ createTaskThreadMessage, sendTaskThreadMessageToAgent }),
      "task-id",
      "@agent investigate this",
    );

    expect(createTaskThreadMessage).toHaveBeenCalledWith(
      "task-id",
      "@agent investigate this",
    );
    expect(sendTaskThreadMessageToAgent).toHaveBeenCalledWith(
      "task-id",
      "message-id",
    );
    expect(createTaskThreadMessage.mock.invocationCallOrder[0]).toBeLessThan(
      sendTaskThreadMessageToAgent.mock.invocationCallOrder[0],
    );
  });

  it("returns the created message when forwarding fails", async () => {
    const sendError = new Error("No active run");
    const service = new TaskThreadService();

    await expect(
      service.postMessageToAgent(
        client({
          createTaskThreadMessage: vi.fn().mockResolvedValue(message()),
          sendTaskThreadMessageToAgent: vi.fn().mockRejectedValue(sendError),
        }),
        "task-id",
        "@agent investigate this",
      ),
    ).resolves.toEqual({ message: message(), sendError });
  });
});
