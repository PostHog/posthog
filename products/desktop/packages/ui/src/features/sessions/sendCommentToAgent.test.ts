import { beforeEach, describe, expect, it, vi } from "vitest";

const send = vi.hoisted(() => vi.fn());
const toastError = vi.hoisted(() => vi.fn());
vi.mock("@posthog/core/sessions/commentToAgent", () => ({
  CommentToAgentService: class {
    send = send;
  },
}));
vi.mock("@posthog/ui/primitives/toast", () => ({
  toast: { error: toastError },
}));
vi.mock("./commentToAgentHost", () => ({ commentToAgentHost: {} }));

import { sendCommentToAgent } from "./sendCommentToAgent";

describe("sendCommentToAgent", () => {
  beforeEach(() => {
    send.mockReset();
    toastError.mockReset();
  });

  it("tells the user when a saved comment could not reach the chat", async () => {
    send.mockRejectedValue(new Error("editor gone"));

    await expect(
      sendCommentToAgent({
        taskId: "task-1",
        comment: "Fix it",
        context: null,
        surface: "task",
      }),
    ).resolves.toBeUndefined();
    expect(toastError).toHaveBeenCalledWith(
      "Couldn't add the comment to chat",
      "Your comment is saved. Copy it into the chat to send it to the agent.",
    );
  });
});
