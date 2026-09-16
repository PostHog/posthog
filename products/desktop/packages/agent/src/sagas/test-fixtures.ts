import type { SagaLogger } from "@posthog/shared";
import { vi } from "vitest";
import type { PostHogAPIClient } from "../posthog-api";
import type { StoredNotification, TaskRun } from "../types";

export { createTestRepo, type TestRepo } from "../test/fixtures/api";

export function createMockLogger(): SagaLogger {
  return {
    info: vi.fn(),
    debug: vi.fn(),
    error: vi.fn(),
    warn: vi.fn(),
  };
}

export function createMockApiClient(
  overrides: Partial<PostHogAPIClient> = {},
): PostHogAPIClient {
  return {
    uploadTaskArtifacts: vi
      .fn()
      .mockResolvedValue([{ storage_path: "gs://bucket/artifacts/test.pack" }]),
    downloadArtifact: vi.fn(),
    getTaskRun: vi.fn(),
    fetchTaskRunLogs: vi.fn(),
    ...overrides,
  } as unknown as PostHogAPIClient;
}

export function createTaskRun(overrides: Partial<TaskRun> = {}): TaskRun {
  return {
    id: "run-1",
    task: "task-1",
    team: 1,
    branch: null,
    stage: null,
    environment: "local",
    status: "in_progress",
    log_url: "https://logs.example.com/run-1",
    error_message: null,
    output: null,
    state: {},
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    completed_at: null,
    ...overrides,
  };
}

export function createNotification(
  method: string,
  params: Record<string, unknown>,
): StoredNotification {
  return {
    type: "notification",
    timestamp: new Date().toISOString(),
    notification: {
      jsonrpc: "2.0",
      method,
      params,
    },
  };
}

export function createUserMessage(content: string): StoredNotification {
  return createNotification("session/update", {
    update: {
      sessionUpdate: "user_message",
      content: { type: "text", text: content },
    },
  });
}

export function createAgentChunk(text: string): StoredNotification {
  return createNotification("session/update", {
    update: {
      sessionUpdate: "agent_message_chunk",
      content: { type: "text", text },
    },
  });
}

export function createAgentMessage(text: string): StoredNotification {
  return createNotification("session/update", {
    update: {
      sessionUpdate: "agent_message",
      content: { type: "text", text },
    },
  });
}

export function createToolCall(
  toolCallId: string,
  toolName: string,
  toolInput: unknown,
): StoredNotification {
  return createNotification("session/update", {
    update: {
      sessionUpdate: "tool_call",
      _meta: {
        claudeCode: { toolCallId, toolName, toolInput },
      },
    },
  });
}

export function createToolResult(
  toolCallId: string,
  toolResponse: unknown,
): StoredNotification {
  return createNotification("session/update", {
    update: {
      sessionUpdate: "tool_result",
      _meta: {
        claudeCode: { toolCallId, toolResponse },
      },
    },
  });
}
