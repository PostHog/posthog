import type { PrReviewComment } from "@posthog/shared";
import { Theme } from "@radix-ui/themes";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { PrCommentMetadata } from "../types";
import { PrCommentThread } from "./PrCommentThread";

const { reply, resolve, sendPromptToAgent } = vi.hoisted(() => ({
  reply: vi.fn(),
  resolve: vi.fn(),
  sendPromptToAgent: vi.fn(),
}));

vi.mock("../hooks/usePrCommentActions", () => ({
  usePrCommentActions: () => ({ reply, resolve }),
}));

vi.mock("../../sessions/sendPromptToAgent", () => ({ sendPromptToAgent }));

function makeComment(): PrReviewComment {
  return {
    id: 42,
    body: "Could this use the shared helper?",
    created_at: "2026-07-14T12:00:00Z",
    user: {
      login: "reviewer",
      avatar_url: "",
    },
  } as PrReviewComment;
}

function makeMetadata(): PrCommentMetadata {
  return {
    kind: "pr-comment",
    threadId: 42,
    nodeId: "thread-node",
    isResolved: false,
    comments: [makeComment()],
    isOutdated: false,
    isFileLevel: false,
    startLine: 8,
    endLine: 8,
    side: "additions",
  };
}

function renderThread() {
  return render(
    <Theme>
      <PrCommentThread
        taskId="task-1"
        prUrl="https://github.com/PostHog/posthog/pull/1"
        filePath="src/example.ts"
        metadata={makeMetadata()}
      />
    </Theme>,
  );
}

describe("PrCommentThread", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    reply.mockResolvedValue(true);
    resolve.mockResolvedValue(true);
    sendPromptToAgent.mockResolvedValue(true);
  });

  it("sends a custom chat message with the review context", async () => {
    const user = userEvent.setup();
    renderThread();

    await user.click(screen.getByRole("button", { name: "Chat" }));
    await user.type(
      screen.getByPlaceholderText("Ask the agent about this comment..."),
      "Check whether this helper already exists",
    );
    await user.click(screen.getByRole("button", { name: "Send" }));

    expect(sendPromptToAgent).toHaveBeenCalledWith(
      "task-1",
      expect.stringContaining("Could this use the shared helper?"),
    );
    expect(sendPromptToAgent).toHaveBeenCalledWith(
      "task-1",
      expect.stringContaining("Check whether this helper already exists"),
    );
    await waitFor(() =>
      expect(
        screen.queryByPlaceholderText("Ask the agent about this comment..."),
      ).not.toBeInTheDocument(),
    );
  });

  it("keeps the custom message available when sending fails", async () => {
    sendPromptToAgent.mockResolvedValue(false);
    const user = userEvent.setup();
    renderThread();

    await user.click(screen.getByRole("button", { name: "Chat" }));
    const textarea = screen.getByPlaceholderText(
      "Ask the agent about this comment...",
    );
    await user.type(textarea, "Keep this draft");
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() =>
      expect(
        screen.getByPlaceholderText("Ask the agent about this comment..."),
      ).toHaveValue("Keep this draft"),
    );
  });

  it("keeps a reply composer opened while a chat message is sending", async () => {
    let resolveSend: ((success: boolean) => void) | undefined;
    sendPromptToAgent.mockReturnValue(
      new Promise<boolean>((resolve) => {
        resolveSend = resolve;
      }),
    );
    const user = userEvent.setup();
    renderThread();

    await user.click(screen.getByRole("button", { name: "Chat" }));
    await user.type(
      screen.getByPlaceholderText("Ask the agent about this comment..."),
      "Check this",
    );
    await user.click(screen.getByRole("button", { name: "Send" }));
    await user.click(screen.getByRole("button", { name: "Close composer" }));
    await user.click(screen.getByRole("button", { name: "Reply" }));
    await user.type(screen.getByPlaceholderText("Write a reply..."), "Keep me");

    resolveSend?.(true);

    await waitFor(() =>
      expect(screen.getByPlaceholderText("Write a reply...")).toHaveValue(
        "Keep me",
      ),
    );
  });

  it("still posts replies without sending them to chat", async () => {
    const user = userEvent.setup();
    renderThread();

    await user.click(screen.getByRole("button", { name: "Reply" }));
    await user.type(screen.getByPlaceholderText("Write a reply..."), "Done");
    await user.click(screen.getByRole("button", { name: "Reply" }));

    expect(reply).toHaveBeenCalledWith(42, "Done");
    expect(sendPromptToAgent).not.toHaveBeenCalled();
  });
});
