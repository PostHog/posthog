import { toast } from "@posthog/ui/primitives/toast";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DEFAULT_TAB_IDS } from "../panels/panelConstants";
import { AGENT_PROMPT_SENDER } from "./agentPromptSender";
import { sendPromptToAgent } from "./sendPromptToAgent";

const { mockSender, reviewState, panelState, findTabInTree } = vi.hoisted(
  () => ({
    mockSender: vi.fn(),
    reviewState: {
      mode: "split" as "split" | "expanded",
      setReviewMode: vi.fn(),
    },
    panelState: {
      taskLayouts: {} as Record<string, { panelTree: unknown }>,
      setActiveTab: vi.fn(),
    },
    findTabInTree: vi.fn(),
  }),
);

vi.mock("@posthog/ui/primitives/toast", () => ({
  toast: { error: vi.fn(), info: vi.fn(), success: vi.fn() },
}));

vi.mock("@posthog/di/container", () => ({
  resolveService: (token: unknown) => {
    if (token === AGENT_PROMPT_SENDER) return mockSender;
    throw new Error(`resolveService: unmocked token ${String(token)}`);
  },
}));

vi.mock("../code-review/reviewNavigationStore", () => ({
  useReviewNavigationStore: {
    getState: () => ({
      getReviewMode: () => reviewState.mode,
      setReviewMode: reviewState.setReviewMode,
    }),
  },
}));

vi.mock("../panels/panelLayoutStore", () => ({
  usePanelLayoutStore: {
    getState: () => ({
      taskLayouts: panelState.taskLayouts,
      setActiveTab: panelState.setActiveTab,
    }),
  },
}));

vi.mock("../panels/panelTree", () => ({ findTabInTree }));

describe("sendPromptToAgent", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    reviewState.mode = "split";
    panelState.taskLayouts = {};
    findTabInTree.mockReturnValue({ panelId: "panel-logs" });
  });

  it.each([
    [
      new Error("Agent server is not reachable"),
      "Agent server is not reachable",
    ],
    ["boom", "Failed to send your message to the agent. Please try again."],
  ])(
    "surfaces a rejected send as an error toast (%#)",
    async (rejection, expectedMessage) => {
      mockSender.mockRejectedValueOnce(rejection);

      const success = await sendPromptToAgent("task-1", "hello");

      expect(success).toBe(false);
      expect(toast.error).toHaveBeenCalledWith(expectedMessage);
    },
  );

  it("does not toast when the send resolves", async () => {
    mockSender.mockResolvedValueOnce(undefined);

    const success = await sendPromptToAgent("task-1", "hello");

    expect(success).toBe(true);
    expect(toast.error).not.toHaveBeenCalled();
  });

  it.each([
    ["resolves", () => mockSender.mockResolvedValueOnce(undefined)],
    ["rejects", () => mockSender.mockRejectedValueOnce(new Error("nope"))],
  ])(
    "collapses review and switches to the logs tab when the send %s",
    (_label, primeSender) => {
      primeSender();
      reviewState.mode = "expanded";
      panelState.taskLayouts = { "task-1": { panelTree: {} } };

      sendPromptToAgent("task-1", "hello");

      expect(reviewState.setReviewMode).toHaveBeenCalledWith("task-1", "split");
      expect(panelState.setActiveTab).toHaveBeenCalledWith(
        "task-1",
        "panel-logs",
        DEFAULT_TAB_IDS.LOGS,
      );
    },
  );
});
