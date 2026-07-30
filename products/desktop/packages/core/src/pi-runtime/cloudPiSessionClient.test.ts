import type { TaskService } from "@posthog/core/task-detail/taskService";
import type { AgentConversationEvent } from "@posthog/shared";
import type { CloudTaskUpdatePayload } from "@posthog/shared/domain-types";
import { describe, expect, it, vi } from "vitest";
import type { CloudTaskClient } from "../cloud-task/cloudTaskClient";
import { CloudPiSessionClient } from "./cloudPiSessionClient";
import {
  PiSessionController,
  type PiSessionProvider,
} from "./piSessionController";

function createCloudTaskClient(autoStart = true) {
  let onUpdate: (update: CloudTaskUpdatePayload) => void = () => {};
  let onError: (error: unknown) => void = () => {};
  let onStarted: () => void = () => {};
  const unsubscribe = vi.fn();
  const client: CloudTaskClient = {
    getContext: vi.fn(async () => null),
    watch: vi.fn(async () => {}),
    unwatch: vi.fn(async () => {}),
    retry: vi.fn(async () => {}),
    subscribe: vi.fn((_taskId, _runId, handler, errorHandler, started) => {
      onUpdate = handler;
      onError = errorHandler;
      onStarted = started;
      if (autoStart) {
        onStarted();
      }
      return unsubscribe;
    }),
    sendCommand: vi.fn(async () => ({ success: false })),
  };

  return {
    client,
    startSubscription: () => onStarted(),
    sendUpdate: (update: CloudTaskUpdatePayload) => onUpdate(update),
    sendError: (error: unknown) => onError(error),
    unsubscribe,
  };
}

function context(status: "queued" | "in_progress" | "completed") {
  return {
    taskId: "task-1",
    runId: "run-1",
    runStatus: status,
    apiHost: "https://us.posthog.com",
    teamId: 1,
  };
}

const snapshotEvent: AgentConversationEvent = {
  type: "assistant_message_chunk",
  timestamp: 1,
  content: { type: "text", text: "durable response" },
};

describe("CloudPiSessionClient", () => {
  it("waits for the native Pi readiness event before startup RPC commands", async () => {
    const cloud = createCloudTaskClient();
    vi.mocked(cloud.client.sendCommand).mockResolvedValue({
      success: true,
      result: {
        type: "response",
        command: "get_state",
        success: true,
        data: { isStreaming: true },
      },
    });
    const session = new CloudPiSessionClient(
      cloud.client,
      context("in_progress"),
    );
    session.onConversationEvent(vi.fn(), vi.fn());

    const state = session.client.getState();
    expect(cloud.client.sendCommand).not.toHaveBeenCalled();

    cloud.sendUpdate({
      taskId: "task-1",
      runId: "run-1",
      kind: "logs",
      newEntries: [{ type: "pi_run_started" }],
      totalEntryCount: 1,
    });

    await expect(state).resolves.toMatchObject({ isStreaming: true });
    expect(cloud.client.sendCommand).toHaveBeenCalledOnce();
  });

  it("does not fail while a sandbox takes longer than 30 seconds to boot", async () => {
    vi.useFakeTimers();
    try {
      const cloud = createCloudTaskClient();
      vi.mocked(cloud.client.sendCommand).mockResolvedValue({
        success: true,
        result: {
          type: "response",
          command: "get_state",
          success: true,
          data: { isStreaming: false },
        },
      });
      const session = new CloudPiSessionClient(
        cloud.client,
        context("in_progress"),
      );
      session.onConversationEvent(vi.fn(), vi.fn());

      const state = session.client.getState();
      await vi.advanceTimersByTimeAsync(60_000);
      expect(cloud.client.sendCommand).not.toHaveBeenCalled();

      cloud.sendUpdate({
        taskId: "task-1",
        runId: "run-1",
        kind: "logs",
        newEntries: [{ type: "pi_run_started" }],
        totalEntryCount: 1,
      });

      await expect(state).resolves.toMatchObject({ isStreaming: false });
    } finally {
      vi.useRealTimers();
    }
  });

  it("waits for a fresh start when a queued resume snapshot contains an old start", async () => {
    const cloud = createCloudTaskClient();
    vi.mocked(cloud.client.sendCommand).mockResolvedValue({
      success: true,
      result: {
        type: "response",
        command: "get_state",
        success: true,
        data: { isStreaming: false },
      },
    });
    const session = new CloudPiSessionClient(cloud.client, context("queued"));
    session.onConversationEvent(vi.fn(), vi.fn());

    const state = session.client.getState();
    cloud.sendUpdate({
      taskId: "task-1",
      runId: "run-1",
      kind: "snapshot",
      status: "queued",
      newEntries: [{ type: "pi_run_started" }],
      totalEntryCount: 1,
    });

    expect(cloud.client.sendCommand).not.toHaveBeenCalled();

    cloud.sendUpdate({
      taskId: "task-1",
      runId: "run-1",
      kind: "logs",
      newEntries: [{ type: "pi_run_started" }],
      totalEntryCount: 2,
    });

    await expect(state).resolves.toMatchObject({ isStreaming: false });
    expect(cloud.client.sendCommand).toHaveBeenCalledOnce();
  });

  it("waits for subscription readiness before watching and only unsubscribes on cleanup", async () => {
    const cloud = createCloudTaskClient(false);
    vi.mocked(cloud.client.watch).mockImplementation(async () => {
      cloud.sendUpdate({
        taskId: "task-1",
        runId: "run-1",
        kind: "snapshot",
        status: "completed",
        newEntries: [{ type: "pi_event", event: snapshotEvent }],
        totalEntryCount: 1,
      });
    });
    const session = new CloudPiSessionClient(
      cloud.client,
      context("completed"),
    );

    const cleanup = session.onConversationEvent(vi.fn(), vi.fn());
    const conversation = session.getConversation();
    expect(cloud.client.watch).not.toHaveBeenCalled();

    cloud.startSubscription();

    await expect(conversation).resolves.toEqual([
      expect.objectContaining(snapshotEvent),
    ]);
    expect(cloud.client.watch).toHaveBeenCalledTimes(1);

    cleanup();
    expect(cloud.unsubscribe).toHaveBeenCalledTimes(1);
    expect(cloud.client.unwatch).not.toHaveBeenCalled();
  });

  it("rejects terminal history when the update subscription fails", async () => {
    const cloud = createCloudTaskClient();
    const session = new CloudPiSessionClient(
      cloud.client,
      context("completed"),
    );
    const onError = vi.fn();
    session.onConversationEvent(vi.fn(), onError);

    const conversation = session.getConversation();
    const error = new Error("subscription failed");
    cloud.sendError(error);

    await expect(conversation).rejects.toThrow("subscription failed");
    expect(onError).toHaveBeenCalledWith(error);
  });

  it("streams provisioning progress before the Pi runtime is ready", () => {
    const cloud = createCloudTaskClient();
    const session = new CloudPiSessionClient(
      cloud.client,
      context("in_progress"),
    );
    const events: AgentConversationEvent[] = [];
    session.onConversationEvent((event) => events.push(event), vi.fn());

    cloud.sendUpdate({
      taskId: "task-1",
      runId: "run-1",
      kind: "logs",
      newEntries: [
        {
          type: "notification",
          timestamp: "2026-07-23T12:00:00.000Z",
          notification: {
            method: "_posthog/progress",
            params: {
              step: "sandbox",
              status: "in_progress",
              label: "Setting up sandbox",
              group: "setup:run-1",
            },
          },
        },
      ],
      totalEntryCount: 1,
    });

    expect(events).toEqual([
      expect.objectContaining({
        type: "progress",
        timestamp: Date.parse("2026-07-23T12:00:00.000Z"),
        step: "sandbox",
        status: "in_progress",
        label: "Setting up sandbox",
        group: "setup:run-1",
      }),
    ]);
    expect(cloud.client.sendCommand).not.toHaveBeenCalled();
  });

  it("normalizes legacy direct bash events at the cloud boundary", async () => {
    const cloud = createCloudTaskClient();
    const session = new CloudPiSessionClient(
      cloud.client,
      context("completed"),
    );
    session.onConversationEvent(vi.fn(), vi.fn());

    const conversation = session.getConversation();
    cloud.sendUpdate({
      taskId: "task-1",
      runId: "run-1",
      kind: "snapshot",
      status: "completed",
      newEntries: [
        {
          type: "pi_event",
          event: {
            type: "tool_call_updated",
            timestamp: 1,
            toolCall: { id: "pi-bash-1", status: "completed" },
          },
        },
      ],
      totalEntryCount: 1,
    });

    await expect(conversation).resolves.toEqual([
      expect.objectContaining({
        type: "tool_call_updated",
        toolCall: expect.objectContaining({ origin: "user_shell" }),
      }),
    ]);
  });

  it("serves persisted native config while the cloud runtime is cold", async () => {
    const cloud = createCloudTaskClient();
    const session = new CloudPiSessionClient(cloud.client, {
      ...context("completed"),
      persistedConfig: {
        model: { provider: "posthog", id: "claude-opus-4-8" },
        thinkingLevel: "high",
      },
    });

    await expect(session.client.getState()).resolves.toMatchObject({
      thinkingLevel: "high",
    });
    expect(session.persistedConfig).toEqual({
      model: { provider: "posthog", id: "claude-opus-4-8" },
      thinkingLevel: "high",
    });
  });

  it("loads terminal history from the cloud snapshot without sandbox RPC", async () => {
    const cloud = createCloudTaskClient();
    const session = new CloudPiSessionClient(
      cloud.client,
      context("completed"),
    );
    const events: AgentConversationEvent[] = [];
    session.onConversationEvent((event) => events.push(event), vi.fn());

    const conversation = session.getConversation();
    cloud.sendUpdate({
      taskId: "task-1",
      runId: "run-1",
      kind: "snapshot",
      status: "completed",
      newEntries: [{ type: "pi_event", event: snapshotEvent }],
      totalEntryCount: 1,
    });

    await expect(conversation).resolves.toEqual([
      expect.objectContaining(snapshotEvent),
    ]);
    expect(session.resumeRequired).toBe(true);
    await expect(session.health()).resolves.toEqual({ state: "cold" });
    await expect(session.client.getState()).resolves.toMatchObject({
      isStreaming: false,
    });
    await expect(session.client.getAvailableModels()).resolves.toEqual([]);
    await expect(session.client.getCommands()).resolves.toEqual([]);
    expect(events).toEqual([
      expect.objectContaining(snapshotEvent),
      expect.objectContaining({ type: "turn_completed" }),
    ]);
    expect(cloud.client.sendCommand).not.toHaveBeenCalled();
  });

  it("does not install streaming state after a terminal snapshot arrives during controller load", async () => {
    const cloud = createCloudTaskClient();
    let resolveState: (result: {
      success: true;
      result: Record<string, unknown>;
    }) => void = () => {};
    const state = new Promise<{
      success: true;
      result: Record<string, unknown>;
    }>((resolve) => {
      resolveState = resolve;
    });
    vi.mocked(cloud.client.sendCommand).mockImplementation(async (input) => {
      if (input.method === "queue_get") {
        return {
          success: true,
          result: { steering: [], followUp: [] },
        };
      }
      const command = input.params?.command as { type: string };
      if (command.type === "get_state") {
        return state;
      }
      return { success: false };
    });
    const session = new CloudPiSessionClient(
      cloud.client,
      context("in_progress"),
    );
    const provider: PiSessionProvider = {
      get: vi.fn(async () => session),
    };
    const controller = new PiSessionController(provider, {} as TaskService);

    const connection = controller.connect("task-1");
    await vi.waitFor(() => {
      expect(cloud.client.subscribe).toHaveBeenCalledTimes(1);
    });
    cloud.sendUpdate({
      taskId: "task-1",
      runId: "run-1",
      kind: "logs",
      newEntries: [{ type: "pi_run_started" }],
      totalEntryCount: 1,
    });
    await vi.waitFor(() => {
      expect(cloud.client.sendCommand).toHaveBeenCalledTimes(3);
    });
    cloud.sendUpdate({
      taskId: "task-1",
      runId: "run-1",
      kind: "snapshot",
      status: "completed",
      newEntries: [{ type: "pi_event", event: snapshotEvent }],
      totalEntryCount: 1,
    });
    resolveState({
      success: true,
      result: {
        type: "response",
        command: "get_state",
        success: true,
        data: {
          thinkingLevel: "off",
          isStreaming: true,
          isCompacting: false,
          steeringMode: "all",
          followUpMode: "all",
          sessionId: "run-1",
          autoCompactionEnabled: true,
          messageCount: 1,
          pendingMessageCount: 0,
        },
      },
    });

    await connection;

    const controllerSession = controller.store.getState().sessions["task-1"];
    expect(controllerSession.events).toContainEqual(
      expect.objectContaining(snapshotEvent),
    );
    expect(controllerSession.status).toMatchObject({ isStreaming: false });
  });

  it("switches to terminal state when the run finishes during an RPC", async () => {
    const cloud = createCloudTaskClient();
    const session = new CloudPiSessionClient(
      cloud.client,
      context("in_progress"),
    );
    session.onConversationEvent(vi.fn(), vi.fn());
    vi.mocked(cloud.client.sendCommand).mockImplementation(async () => {
      cloud.sendUpdate({
        taskId: "task-1",
        runId: "run-1",
        kind: "snapshot",
        status: "completed",
        newEntries: [{ type: "pi_event", event: snapshotEvent }],
        totalEntryCount: 1,
      });
      return { success: false, retryable: true };
    });
    cloud.sendUpdate({
      taskId: "task-1",
      runId: "run-1",
      kind: "logs",
      newEntries: [{ type: "pi_run_started" }],
      totalEntryCount: 1,
    });

    await expect(session.client.getState()).resolves.toMatchObject({
      isStreaming: false,
    });
    await expect(session.getConversation()).resolves.toEqual([
      expect.objectContaining(snapshotEvent),
    ]);
    expect(cloud.client.sendCommand).toHaveBeenCalledTimes(1);
  });

  it("keeps sessions compatible with queue-unaware cloud runtimes", async () => {
    const cloud = createCloudTaskClient();
    vi.mocked(cloud.client.sendCommand).mockResolvedValue({
      success: false,
      error: "Unknown method: queue_get",
    });
    const session = new CloudPiSessionClient(
      cloud.client,
      context("in_progress"),
    );
    session.onConversationEvent(vi.fn(), vi.fn());
    cloud.sendUpdate({
      taskId: "task-1",
      runId: "run-1",
      kind: "logs",
      newEntries: [{ type: "pi_run_started" }],
      totalEntryCount: 1,
    });

    await expect(session.getQueue()).resolves.toEqual({
      steering: [],
      followUp: [],
    });
  });

  it("preserves structured backend failure details", () => {
    const cloud = createCloudTaskClient();
    const session = new CloudPiSessionClient(
      cloud.client,
      context("in_progress"),
    );
    const onError = vi.fn();
    session.onConversationEvent(vi.fn(), onError);

    cloud.sendUpdate({
      taskId: "task-1",
      runId: "run-1",
      kind: "status",
      status: "failed",
      errorMessage: "Sandbox image does not support Pi",
    });

    expect(onError).toHaveBeenCalledWith(
      expect.objectContaining({
        title: "Cloud run failed",
        message: "Sandbox image does not support Pi",
        retryable: true,
      }),
    );
  });

  it("processes reconnect snapshots and clears streaming on terminal status", async () => {
    const cloud = createCloudTaskClient();
    const session = new CloudPiSessionClient(
      cloud.client,
      context("in_progress"),
    );
    const events: AgentConversationEvent[] = [];
    session.onConversationEvent((event) => events.push(event), vi.fn());

    cloud.sendUpdate({
      taskId: "task-1",
      runId: "run-1",
      kind: "snapshot",
      status: "in_progress",
      newEntries: [{ type: "pi_event", event: snapshotEvent }],
      totalEntryCount: 1,
    });
    cloud.sendUpdate({
      taskId: "task-1",
      runId: "run-1",
      kind: "snapshot",
      status: "in_progress",
      newEntries: [{ type: "pi_event", event: snapshotEvent }],
      totalEntryCount: 1,
    });
    cloud.sendUpdate({
      taskId: "task-1",
      runId: "run-1",
      kind: "status",
      status: "failed",
    });

    expect(events).toEqual([
      expect.objectContaining(snapshotEvent),
      expect.objectContaining({ type: "turn_completed" }),
    ]);
    await expect(session.client.abort()).rejects.toThrow(
      "Cloud task run run-1 is failed",
    );
    expect(cloud.client.sendCommand).not.toHaveBeenCalled();
  });
});
