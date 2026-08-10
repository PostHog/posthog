import type { PiRemoteRpcClient } from "@posthog/agent/pi/remote-rpc-client";
import { describe, expect, it, vi } from "vitest";
import type { CloudTaskClient } from "../cloud-task/cloudTaskClient";
import type { TaskService } from "../task-detail/taskService";
import type { PiSession, PiSessionFactory } from "./piSessionController";
import { RoutingPiSessionProvider } from "./piSessionProvider";

function localSession(): PiSession {
  const client = {
    getState: vi.fn(async () => ({ isStreaming: false })),
    getAvailableModels: vi.fn(async () => []),
    getCommands: vi.fn(async () => []),
    prompt: vi.fn(async () => {}),
    steer: vi.fn(async () => {}),
    followUp: vi.fn(async () => {}),
    compact: vi.fn(async () => undefined),
    setModel: vi.fn(async () => ({ provider: "posthog", id: "model" })),
    setThinkingLevel: vi.fn(async () => {}),
    bash: vi.fn(async () => undefined),
    abort: vi.fn(async () => {}),
    abortBash: vi.fn(async () => {}),
  } as unknown as PiRemoteRpcClient;

  return {
    client,
    health: vi.fn(async () => ({ state: "idle" as const })),
    getConversation: vi.fn(async () => []),
    getQueue: vi.fn(async () => ({ steering: [], followUp: [] })),
    clearQueue: vi.fn(async () => ({ steering: [], followUp: [] })),
    onConversationEvent: vi.fn(() => () => {}),
  };
}

function localFactory(session: PiSession): PiSessionFactory {
  return {
    get: vi.fn(async () => session),
  };
}

function cloudTaskClient(): CloudTaskClient {
  return {
    getContext: vi.fn(async () => ({
      apiHost: "https://us.posthog.com",
      teamId: 1,
    })),
    watch: vi.fn(async () => {}),
    unwatch: vi.fn(async () => {}),
    retry: vi.fn(async () => {}),
    subscribe: vi.fn((taskId, runId, onUpdate) => {
      onUpdate({
        taskId,
        runId,
        kind: "logs",
        newEntries: [{ type: "pi_run_started" }],
        totalEntryCount: 1,
      });
      return () => {};
    }),
    sendCommand: vi.fn(async (input) => ({
      success: true,
      result: {
        type: "response",
        command: input.params?.command
          ? (input.params.command as { type: string }).type
          : "unknown",
        success: true,
      },
    })),
  };
}

function taskService(environment: "local" | "cloud"): TaskService {
  return {
    getCloudPiTaskSessionStorage: vi.fn(async () => null),
    getTask: vi.fn(async () => ({
      id: "task-1",
      runtime: "pi",
      latest_run:
        environment === "cloud"
          ? { id: "run-1", environment: "cloud", status: "in_progress" }
          : null,
    })),
  } as unknown as TaskService;
}

describe("RoutingPiSessionProvider", () => {
  it("returns a cloud session bound to its task run", async () => {
    const local = localSession();
    const cloudTasks = cloudTaskClient();
    const provider = new RoutingPiSessionProvider(
      localFactory(local),
      cloudTasks,
      taskService("cloud"),
    );

    const session = await provider.get("task-1");
    session.onConversationEvent(vi.fn(), vi.fn());
    await session.client.steer("change direction");

    expect(cloudTasks.sendCommand).toHaveBeenCalledWith({
      taskId: "task-1",
      runId: "run-1",
      apiHost: "https://us.posthog.com",
      teamId: 1,
      id: expect.any(String),
      method: "user_message",
      params: {
        content: "change direction",
        artifact_ids: [],
        steer: true,
      },
    });
    expect(local.client.steer).not.toHaveBeenCalled();
  });

  it("reads persisted configuration through Pi's session reader", async () => {
    const local = localSession();
    const localSessions = {
      ...localFactory(local),
      readSessionConfig: vi.fn(async () => ({
        model: { provider: "posthog", id: "claude-opus-4-8" },
        thinkingLevel: "high" as const,
      })),
    };
    const provider = new RoutingPiSessionProvider(
      localSessions,
      cloudTaskClient(),
      {
        ...taskService("cloud"),
        getCloudPiTaskSessionStorage: vi.fn(async () => ({
          id: "session-1",
          download_url: "https://storage.example/session.jsonl",
          content_sha256: "hash",
        })),
      } as unknown as TaskService,
    );

    const session = await provider.get("task-1");

    expect(localSessions.readSessionConfig).toHaveBeenCalledWith(
      "https://storage.example/session.jsonl",
    );
    expect(session.persistedConfig).toEqual({
      model: { provider: "posthog", id: "claude-opus-4-8" },
      thinkingLevel: "high",
    });
  });

  it("binds explicit historical runs and invalidates changed run context", async () => {
    const local = localSession();
    const cloudTasks = cloudTaskClient();
    const getTask = vi.fn(async (_taskId: string, taskRunId?: string) => ({
      id: "task-1",
      runtime: "pi" as const,
      latest_run: {
        id: taskRunId ?? "run-latest",
        environment: "cloud" as const,
        status: "in_progress" as const,
      },
    }));
    const provider = new RoutingPiSessionProvider(
      localFactory(local),
      cloudTasks,
      {
        getTask,
        getCloudPiTaskSessionStorage: vi.fn(async () => null),
      } as unknown as TaskService,
    );

    const historical = await provider.get("task-1", "run-old");
    historical.onConversationEvent(vi.fn(), vi.fn());
    await historical.client.abort();
    const replacement = await provider.get("task-1", "run-new");
    replacement.onConversationEvent(vi.fn(), vi.fn());
    await replacement.client.abort();

    expect(getTask).toHaveBeenNthCalledWith(1, "task-1", "run-old");
    expect(getTask).toHaveBeenNthCalledWith(2, "task-1", "run-new");
    expect(cloudTasks.sendCommand).toHaveBeenNthCalledWith(
      1,
      expect.objectContaining({ runId: "run-old" }),
    );
    expect(cloudTasks.sendCommand).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({ runId: "run-new" }),
    );
  });

  it("delegates local session lifetime to the controller", async () => {
    const local = localSession();
    const localSessions = localFactory(local);
    const cloudTasks = cloudTaskClient();
    const tasks = taskService("local");
    const provider = new RoutingPiSessionProvider(
      localSessions,
      cloudTasks,
      tasks,
    );

    const first = await provider.get("task-1");
    const second = await provider.get("task-1");

    expect(first).toBe(local);
    expect(second).toBe(local);
    expect(localSessions.get).toHaveBeenCalledTimes(2);
  });
});
