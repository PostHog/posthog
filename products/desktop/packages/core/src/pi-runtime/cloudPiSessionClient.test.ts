import type { TaskService } from "@posthog/core/task-detail/taskService";
import {
  type AgentConversationEvent,
  mcpToolKey,
  posthogToolMeta,
} from "@posthog/shared";
import type { CloudTaskUpdatePayload } from "@posthog/shared/domain-types";
import { describe, expect, it, vi } from "vitest";
import type { CloudTaskClient } from "../cloud-task/cloudTaskClient";
import { CloudPiSessionClient } from "./cloudPiSessionClient";
import {
  PiSessionController,
  type PiSessionProvider,
} from "./piSessionController";

function createCloudTaskClient(autoStart = true) {
  const subscriptions: Array<{
    onUpdate: (update: CloudTaskUpdatePayload) => void;
    onError: (error: unknown) => void;
    onStarted: () => void;
  }> = [];
  const unsubscribe = vi.fn();
  const client: CloudTaskClient = {
    getContext: vi.fn(async () => null),
    watch: vi.fn(async () => {}),
    unwatch: vi.fn(async () => {}),
    retry: vi.fn(async () => {}),
    subscribe: vi.fn((_taskId, _runId, onUpdate, onError, onStarted) => {
      subscriptions.push({ onUpdate, onError, onStarted });
      if (autoStart) {
        onStarted();
      }
      return unsubscribe;
    }),
    sendCommand: vi.fn(async () => ({ success: false })),
  };

  return {
    client,
    startSubscription: () => {
      for (const subscription of subscriptions) {
        subscription.onStarted();
      }
    },
    sendUpdate: (update: CloudTaskUpdatePayload) => {
      for (const subscription of subscriptions) {
        subscription.onUpdate(update);
      }
    },
    sendError: (error: unknown) => {
      for (const subscription of subscriptions) {
        subscription.onError(error);
      }
    },
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
  it("relays MCP permission requests and responses through the cloud task", async () => {
    const cloud = createCloudTaskClient();
    const session = new CloudPiSessionClient(
      cloud.client,
      context("in_progress"),
    );
    const onRequest = vi.fn();
    session.onMcpToolPermissionRequest(onRequest, vi.fn());

    const mcp = { server: "Cloudflare", tool: "search" };
    cloud.sendUpdate({
      taskId: "task-1",
      runId: "run-1",
      kind: "permission_request",
      requestId: "request-1",
      toolCall: {
        toolCallId: "request-1",
        title: "Search Cloudflare",
        kind: "other",
        content: [
          {
            type: "content",
            content: { type: "text", text: "Search Cloudflare resources" },
          },
        ],
        rawInput: { query: "workers" },
        _meta: posthogToolMeta({
          toolName: mcpToolKey(mcp),
          mcp,
          mcpInstallationId: "installation-1",
        }),
      },
      options: [],
    });

    const request = {
      requestId: "request-1",
      serverName: "Cloudflare",
      toolName: "search",
      installationId: "installation-1",
      arguments: { query: "workers" },
      description: "Search Cloudflare resources",
    };
    expect(onRequest).toHaveBeenCalledWith(request);

    vi.mocked(cloud.client.sendCommand).mockResolvedValue({ success: true });
    await session.respondMcpToolPermission(request, "allow_always");

    const commandInput = vi.mocked(cloud.client.sendCommand).mock.calls[0]?.[0];
    expect(commandInput).toMatchObject({
      taskId: "task-1",
      runId: "run-1",
      apiHost: "https://us.posthog.com",
      teamId: 1,
      method: "pi/rpc",
      params: {
        command: {
          type: "mcp_permission_response",
          requestId: "request-1",
          decision: "allow_always",
        },
      },
    });
    expect(commandInput?.id).toBe(
      (commandInput?.params?.command as { id?: string }).id,
    );
  });

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

  it("uses the readiness snapshot when opening an already-running session", async () => {
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
    cloud.sendUpdate({
      taskId: "task-1",
      runId: "run-1",
      kind: "snapshot",
      status: "in_progress",
      newEntries: [{ type: "pi_run_started" }],
      totalEntryCount: 1,
    });

    await expect(state).resolves.toMatchObject({ isStreaming: false });
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

  it("waits for a fresh start when a resume snapshot's sandbox has stopped", async () => {
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
      status: "in_progress",
      sandboxAlive: false,
      newEntries: [{ type: "pi_run_started" }],
      totalEntryCount: 1,
    });

    await new Promise<void>((resolve) => setTimeout(resolve, 0));
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

  it("becomes ready from a live snapshot when the fetched status was stale", async () => {
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
      status: "in_progress",
      sandboxAlive: true,
      newEntries: [{ type: "pi_run_started" }],
      totalEntryCount: 1,
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
    const eventContexts: Array<{ isLive: boolean } | undefined> = [];
    session.onConversationEvent((event, context) => {
      events.push(event);
      eventContexts.push(context);
    }, vi.fn());

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
    expect(eventContexts).toEqual([{ isLive: true }]);
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
    const eventContexts: Array<{ isLive: boolean } | undefined> = [];
    session.onConversationEvent((event, context) => {
      events.push(event);
      eventContexts.push(context);
    }, vi.fn());

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
      expect.objectContaining({
        type: "turn_completed",
        stopReason: "end_turn",
      }),
    ]);
    expect(eventContexts).toEqual([{ isLive: false }, { isLive: false }]);
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
      expect(cloud.client.subscribe).toHaveBeenCalledTimes(2);
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
