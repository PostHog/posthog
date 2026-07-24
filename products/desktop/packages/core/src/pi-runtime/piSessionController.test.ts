import type { TaskService } from "@posthog/core/task-detail/taskService";
import type { AgentConversationEvent } from "@posthog/shared";
import { describe, expect, it, vi } from "vitest";
import {
  type PiSessionClient,
  PiSessionController,
} from "./piSessionController";

function createController(
  client = createClient(),
  taskService = {
    openTask: vi.fn(async () => ({ success: true })),
  } as unknown as TaskService,
): PiSessionController {
  return new PiSessionController(client, taskService);
}

function createClient(): PiSessionClient {
  return {
    health: vi.fn(async () => ({ state: "idle" as const })),
    conversation: vi.fn(async () => []),
    status: vi.fn(async () => ({
      thinkingLevel: "off" as const,
      isStreaming: false,
      isCompacting: false,
      steeringMode: "all" as const,
      followUpMode: "all" as const,
      sessionId: "session-1",
      autoCompactionEnabled: true,
      messageCount: 0,
      pendingMessageCount: 0,
    })),
    availableModels: vi.fn(async () => []),
    commands: vi.fn(async () => []),
    subscribe: vi.fn(() => () => {}),
    prompt: vi.fn(async () => {}),
    steer: vi.fn(async () => {}),
    followUp: vi.fn(async () => {}),
    compact: vi.fn(async () => undefined),
    setModel: vi.fn(async (_taskId, provider, id) => ({ provider, id })),
    setThinkingLevel: vi.fn(async () => {}),
    setSteeringMode: vi.fn(async () => {}),
    setFollowUpMode: vi.fn(async () => {}),
    bash: vi.fn(async () => undefined),
    abort: vi.fn(async () => {}),
    abortBash: vi.fn(async () => {}),
  };
}

describe("PiSessionController", () => {
  it.each([
    {
      text: "hello",
      streaming: false,
      mode: "steer" as const,
      action: "prompt",
    },
    { text: "hello", streaming: true, mode: "steer" as const, action: "steer" },
    {
      text: "hello",
      streaming: true,
      mode: "queue" as const,
      action: "followUp",
    },
    {
      text: "/compact keep details",
      streaming: false,
      mode: "steer" as const,
      action: "compact",
    },
  ])("classifies $action submissions", ({ text, streaming, mode, action }) => {
    const controller = createController();

    expect(controller.getSubmitAction(text, streaming, mode)).toBe(action);
  });

  it.each([
    {
      text: "hello",
      streaming: false,
      mode: "steer" as const,
      method: "prompt" as const,
      expectedArgs: ["task-1", "hello"],
    },
    {
      text: "hello",
      streaming: true,
      mode: "steer" as const,
      method: "steer" as const,
      expectedArgs: ["task-1", "hello"],
    },
    {
      text: "hello",
      streaming: true,
      mode: "queue" as const,
      method: "followUp" as const,
      expectedArgs: ["task-1", "hello"],
    },
    {
      text: "/compact keep details",
      streaming: false,
      mode: "steer" as const,
      method: "compact" as const,
      expectedArgs: ["task-1", "keep details"],
    },
  ])("routes submissions through $method", async (input) => {
    const client = createClient();
    const controller = createController(client);

    await controller.submit("task-1", input.text, input.streaming, input.mode);

    expect(client[input.method]).toHaveBeenCalledWith(...input.expectedArgs);
  });

  it("opens cold tasks before connecting", async () => {
    const client = createClient();
    vi.mocked(client.health).mockResolvedValue({ state: "cold" });
    const openTask = vi.fn(async () => ({ success: true }));
    const taskService = { openTask } as unknown as TaskService;
    const controller = createController(client, taskService);

    await controller.ensureConnected("task-1");

    expect(openTask).toHaveBeenCalledWith("task-1");
    expect(controller.store.getState().sessions["task-1"]).toMatchObject({
      connectionState: "connected",
    });
  });

  it("makes the transcript available before model discovery finishes", async () => {
    let resolveModels: (models: []) => void = () => {};
    const models = new Promise<[]>((resolve) => {
      resolveModels = resolve;
    });
    const initialEvent: AgentConversationEvent = {
      type: "assistant_thought_chunk",
      timestamp: 1,
      content: { type: "text", text: "working" },
    };
    const client = createClient();
    vi.mocked(client.conversation).mockResolvedValue([initialEvent]);
    vi.mocked(client.status).mockResolvedValue({
      thinkingLevel: "high",
      isStreaming: true,
      isCompacting: false,
      steeringMode: "all",
      followUpMode: "all",
      sessionId: "session-1",
      autoCompactionEnabled: true,
      messageCount: 1,
      pendingMessageCount: 0,
    });
    vi.mocked(client.availableModels).mockReturnValue(models);
    const controller = createController(client);

    const connection = controller.connect("task-1");

    await vi.waitFor(() => {
      expect(controller.store.getState().sessions["task-1"]).toMatchObject({
        events: [initialEvent],
        status: { isStreaming: true },
      });
    });

    resolveModels([]);
    await connection;
  });

  it("loads session state and appends normalized runtime events", async () => {
    const initialEvent: AgentConversationEvent = {
      type: "assistant_message_chunk",
      timestamp: 1,
      content: { type: "text", text: "hello" },
    };
    const liveEvent: AgentConversationEvent = {
      type: "runtime_status",
      timestamp: 2,
      status: "compacting",
    };
    let onEvent: (event: AgentConversationEvent) => void = () => {};
    const client = createClient();
    vi.mocked(client.conversation).mockResolvedValue([initialEvent]);
    vi.mocked(client.subscribe).mockImplementation((_taskId, handler) => {
      onEvent = handler;
      return () => {};
    });
    const controller = createController(client);

    await controller.connect("task-1");
    onEvent(liveEvent);

    expect(controller.store.getState().sessions["task-1"]).toMatchObject({
      events: [initialEvent, liveEvent],
      status: { isCompacting: true },
    });
  });
});
