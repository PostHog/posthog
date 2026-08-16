import type { LlmGatewayService } from "@posthog/core/llm-gateway/llm-gateway";
import { describe, expect, it, vi } from "vitest";
import { SideChatService } from "./sideChatService";

function response(content: string) {
  return {
    content,
    model: "test-model",
    stopReason: "end_turn",
    usage: { inputTokens: 10, outputTokens: 5 },
  };
}

describe("SideChatService", () => {
  it("keeps side-chat history separate while refreshing the main-chat context", async () => {
    const prompt = vi
      .fn()
      .mockResolvedValueOnce(response("First answer"))
      .mockResolvedValueOnce(response("Second answer"));
    const service = new SideChatService({
      prompt,
    } as unknown as LlmGatewayService);

    await service.ask("task-1", "First question", "Main context one");
    await service.ask("task-1", "Follow up", "Main context two");

    expect(service.store.getState().threads["task-1"]?.messages).toEqual([
      { id: "side-chat-1", role: "user", content: "First question" },
      { id: "side-chat-2", role: "assistant", content: "First answer" },
      { id: "side-chat-3", role: "user", content: "Follow up" },
      { id: "side-chat-4", role: "assistant", content: "Second answer" },
    ]);
    expect(prompt.mock.calls[1]?.[0]).toEqual([
      { role: "user", content: "First question" },
      { role: "assistant", content: "First answer" },
      { role: "user", content: "Follow up" },
    ]);
    expect(prompt.mock.calls[1]?.[1].system).toContain("Main context two");
  });

  it("ignores a second submission while an answer is in flight", async () => {
    let resolvePrompt:
      | ((value: ReturnType<typeof response>) => void)
      | undefined;
    const prompt = vi.fn(
      () =>
        new Promise<ReturnType<typeof response>>((resolve) => {
          resolvePrompt = resolve;
        }),
    );
    const service = new SideChatService({
      prompt,
    } as unknown as LlmGatewayService);

    const first = service.ask("task-1", "First question", "Main context");
    await service.ask("task-1", "Duplicate question", "Main context");
    resolvePrompt?.(response("Answer"));
    await first;

    expect(prompt).toHaveBeenCalledOnce();
    expect(service.store.getState().threads["task-1"]?.messages).toHaveLength(
      2,
    );
  });
});
