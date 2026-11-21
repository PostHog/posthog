import type { SagaLogger } from "@posthog/agent-contracts";
import { vi } from "vitest";
import type { StoredNotification } from "../types";

export {
  createMockApiClient,
  createTestRepo,
  type TestRepo,
} from "../test/fixtures/api";

export function createMockLogger(): SagaLogger {
  return {
    info: vi.fn(),
    debug: vi.fn(),
    error: vi.fn(),
    warn: vi.fn(),
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
