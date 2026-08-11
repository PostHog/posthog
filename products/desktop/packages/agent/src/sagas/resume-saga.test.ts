import type { SagaLogger } from "@posthog/shared";
import { afterEach, beforeEach, describe, expect, it, type vi } from "vitest";
import { POSTHOG_NOTIFICATIONS } from "../acp-extensions";
import type { PostHogAPIClient } from "../posthog-api";
import { ResumeSaga } from "./resume-saga";
import {
  createAgentChunk,
  createAgentMessage,
  createGitCheckpointNotification,
  createMockApiClient,
  createMockLogger,
  createNotification,
  createTaskRun,
  createTestRepo,
  createToolCall,
  createToolResult,
  createUserMessage,
  type TestRepo,
} from "./test-fixtures";

describe("ResumeSaga", () => {
  let repo: TestRepo;
  let mockLogger: SagaLogger;
  let mockApiClient: PostHogAPIClient;

  beforeEach(async () => {
    repo = await createTestRepo("resume-saga");
    mockLogger = createMockLogger();
    mockApiClient = createMockApiClient();
  });

  afterEach(async () => {
    await repo.cleanup();
  });

  describe("empty state handling", () => {
    it("returns empty result when task run has no log URL", async () => {
      (mockApiClient.getTaskRun as ReturnType<typeof vi.fn>).mockResolvedValue(
        createTaskRun({ log_url: "" }),
      );

      const saga = new ResumeSaga(mockLogger);
      const result = await saga.run({
        taskId: "task-1",
        runId: "run-1",
        repositoryPath: repo.path,
        apiClient: mockApiClient,
      });

      expect(result.success).toBe(true);
      if (result.success) {
        expect(result.data.conversation).toHaveLength(0);
        expect(result.data.latestGitCheckpoint).toBeNull();
        expect(result.data.logEntryCount).toBe(0);
      }
    });

    it("returns empty result when log has no entries", async () => {
      (mockApiClient.getTaskRun as ReturnType<typeof vi.fn>).mockResolvedValue(
        createTaskRun(),
      );
      (
        mockApiClient.fetchTaskRunLogs as ReturnType<typeof vi.fn>
      ).mockResolvedValue([]);

      const saga = new ResumeSaga(mockLogger);
      const result = await saga.run({
        taskId: "task-1",
        runId: "run-1",
        repositoryPath: repo.path,
        apiClient: mockApiClient,
      });

      expect(result.success).toBe(true);
      if (result.success) {
        expect(result.data.conversation).toHaveLength(0);
        expect(result.data.logEntryCount).toBe(0);
      }
    });
  });

  describe("conversation rebuilding", () => {
    it("rebuilds user and assistant turns", async () => {
      (mockApiClient.getTaskRun as ReturnType<typeof vi.fn>).mockResolvedValue(
        createTaskRun(),
      );
      (
        mockApiClient.fetchTaskRunLogs as ReturnType<typeof vi.fn>
      ).mockResolvedValue([
        createUserMessage("Hello"),
        createAgentChunk("Hi there!"),
        createUserMessage("Help me"),
        createAgentChunk("Sure, "),
        createAgentChunk("I can help."),
      ]);

      const saga = new ResumeSaga(mockLogger);
      const result = await saga.run({
        taskId: "task-1",
        runId: "run-1",
        repositoryPath: repo.path,
        apiClient: mockApiClient,
      });

      expect(result.success).toBe(true);
      if (!result.success) return;

      expect(result.data.conversation).toHaveLength(4);
      expect(result.data.conversation[0].role).toBe("user");
      expect(result.data.conversation[1].role).toBe("assistant");
      expect(result.data.conversation[2].role).toBe("user");
      expect(result.data.conversation[3].role).toBe("assistant");
    });

    it("merges consecutive text chunks", async () => {
      (mockApiClient.getTaskRun as ReturnType<typeof vi.fn>).mockResolvedValue(
        createTaskRun(),
      );
      (
        mockApiClient.fetchTaskRunLogs as ReturnType<typeof vi.fn>
      ).mockResolvedValue([
        createAgentChunk("Hello "),
        createAgentChunk("world"),
        createAgentChunk("!"),
      ]);

      const saga = new ResumeSaga(mockLogger);
      const result = await saga.run({
        taskId: "task-1",
        runId: "run-1",
        repositoryPath: repo.path,
        apiClient: mockApiClient,
      });

      expect(result.success).toBe(true);
      if (!result.success) return;

      expect(result.data.conversation).toHaveLength(1);
      const content = result.data.conversation[0].content[0];
      expect(content).toEqual({ type: "text", text: "Hello world!" });
    });

    it("rebuilds from coalesced agent_message events", async () => {
      (mockApiClient.getTaskRun as ReturnType<typeof vi.fn>).mockResolvedValue(
        createTaskRun(),
      );
      (
        mockApiClient.fetchTaskRunLogs as ReturnType<typeof vi.fn>
      ).mockResolvedValue([
        createUserMessage("Hello"),
        createAgentMessage("Hi there! Let me help."),
        createUserMessage("Thanks"),
        createAgentMessage("Sure thing."),
      ]);

      const saga = new ResumeSaga(mockLogger);
      const result = await saga.run({
        taskId: "task-1",
        runId: "run-1",
        repositoryPath: repo.path,
        apiClient: mockApiClient,
      });

      expect(result.success).toBe(true);
      if (!result.success) return;

      expect(result.data.conversation).toHaveLength(4);
      expect(result.data.conversation[0].role).toBe("user");
      expect(result.data.conversation[1].role).toBe("assistant");
      expect(result.data.conversation[1].content[0]).toEqual({
        type: "text",
        text: "Hi there! Let me help.",
      });
      expect(result.data.conversation[3].content[0]).toEqual({
        type: "text",
        text: "Sure thing.",
      });
    });

    it("merges multiple agent_message events within a single turn", async () => {
      (mockApiClient.getTaskRun as ReturnType<typeof vi.fn>).mockResolvedValue(
        createTaskRun(),
      );
      (
        mockApiClient.fetchTaskRunLogs as ReturnType<typeof vi.fn>
      ).mockResolvedValue([
        createUserMessage("Fix the bug"),
        createAgentMessage("I'll look into this."),
        createToolCall("call-1", "ReadFile", { path: "/bug.ts" }),
        createToolResult("call-1", "buggy code"),
        createAgentMessage(" Here's the fix."),
        createToolCall("call-2", "Edit", { path: "/bug.ts" }),
        createToolResult("call-2", "done"),
        createAgentMessage(" All fixed now."),
      ]);

      const saga = new ResumeSaga(mockLogger);
      const result = await saga.run({
        taskId: "task-1",
        runId: "run-1",
        repositoryPath: repo.path,
        apiClient: mockApiClient,
      });

      expect(result.success).toBe(true);
      if (!result.success) return;

      expect(result.data.conversation).toHaveLength(2);
      const assistantTurn = result.data.conversation[1];
      expect(assistantTurn.role).toBe("assistant");
      // All text segments should merge into one block
      expect(assistantTurn.content).toHaveLength(1);
      expect(assistantTurn.content[0]).toEqual({
        type: "text",
        text: "I'll look into this. Here's the fix. All fixed now.",
      });
      expect(assistantTurn.toolCalls).toHaveLength(2);
    });

    it("produces same result from chunks and coalesced messages", async () => {
      const chunkEntries = [
        createUserMessage("Hello"),
        createAgentChunk("First "),
        createAgentChunk("part."),
        createToolCall("call-1", "Read", { path: "/a" }),
        createToolResult("call-1", "content"),
        createAgentChunk("Second "),
        createAgentChunk("part."),
      ];

      const coalescedEntries = [
        createUserMessage("Hello"),
        createAgentMessage("First part."),
        createToolCall("call-1", "Read", { path: "/a" }),
        createToolResult("call-1", "content"),
        createAgentMessage("Second part."),
      ];

      // Run with chunks (old format)
      (mockApiClient.getTaskRun as ReturnType<typeof vi.fn>).mockResolvedValue(
        createTaskRun(),
      );
      (
        mockApiClient.fetchTaskRunLogs as ReturnType<typeof vi.fn>
      ).mockResolvedValue(chunkEntries);

      const saga1 = new ResumeSaga(mockLogger);
      const result1 = await saga1.run({
        taskId: "task-1",
        runId: "run-1",
        repositoryPath: repo.path,
        apiClient: mockApiClient,
      });

      // Run with coalesced (new format)
      (
        mockApiClient.fetchTaskRunLogs as ReturnType<typeof vi.fn>
      ).mockResolvedValue(coalescedEntries);

      const saga2 = new ResumeSaga(mockLogger);
      const result2 = await saga2.run({
        taskId: "task-1",
        runId: "run-1",
        repositoryPath: repo.path,
        apiClient: mockApiClient,
      });

      expect(result1.success).toBe(true);
      expect(result2.success).toBe(true);
      if (!result1.success || !result2.success) return;

      // Conversation structure should be identical
      expect(result1.data.conversation.length).toBe(
        result2.data.conversation.length,
      );
      for (let i = 0; i < result1.data.conversation.length; i++) {
        expect(result1.data.conversation[i].role).toBe(
          result2.data.conversation[i].role,
        );
        expect(result1.data.conversation[i].content).toEqual(
          result2.data.conversation[i].content,
        );
      }
    });

    it("tracks tool calls with results", async () => {
      (mockApiClient.getTaskRun as ReturnType<typeof vi.fn>).mockResolvedValue(
        createTaskRun(),
      );
      (
        mockApiClient.fetchTaskRunLogs as ReturnType<typeof vi.fn>
      ).mockResolvedValue([
        createToolCall("call-1", "ReadFile", { path: "/test.ts" }),
        createToolResult("call-1", "file contents here"),
      ]);

      const saga = new ResumeSaga(mockLogger);
      const result = await saga.run({
        taskId: "task-1",
        runId: "run-1",
        repositoryPath: repo.path,
        apiClient: mockApiClient,
      });

      expect(result.success).toBe(true);
      if (!result.success) return;

      expect(result.data.conversation).toHaveLength(1);
      const turn = result.data.conversation[0];
      expect(turn.toolCalls).toHaveLength(1);
      expect(turn.toolCalls?.[0]).toMatchObject({
        toolCallId: "call-1",
        toolName: "ReadFile",
        input: { path: "/test.ts" },
        result: "file contents here",
      });
    });

    it("handles multiple tool calls in sequence", async () => {
      (mockApiClient.getTaskRun as ReturnType<typeof vi.fn>).mockResolvedValue(
        createTaskRun(),
      );
      (
        mockApiClient.fetchTaskRunLogs as ReturnType<typeof vi.fn>
      ).mockResolvedValue([
        createToolCall("call-1", "ReadFile", { path: "/a.ts" }),
        createToolResult("call-1", "content a"),
        createToolCall("call-2", "WriteFile", {
          path: "/b.ts",
          content: "new",
        }),
        createToolResult("call-2", "written"),
      ]);

      const saga = new ResumeSaga(mockLogger);
      const result = await saga.run({
        taskId: "task-1",
        runId: "run-1",
        repositoryPath: repo.path,
        apiClient: mockApiClient,
      });

      expect(result.success).toBe(true);
      if (!result.success) return;

      expect(result.data.conversation[0].toolCalls).toHaveLength(2);
    });

    it("handles orphaned tool calls (no result due to interruption)", async () => {
      (mockApiClient.getTaskRun as ReturnType<typeof vi.fn>).mockResolvedValue(
        createTaskRun(),
      );
      (
        mockApiClient.fetchTaskRunLogs as ReturnType<typeof vi.fn>
      ).mockResolvedValue([
        createAgentChunk("Let me read the file"),
        createToolCall("call-1", "ReadFile", { path: "/test.ts" }),
      ]);

      const saga = new ResumeSaga(mockLogger);
      const result = await saga.run({
        taskId: "task-1",
        runId: "run-1",
        repositoryPath: repo.path,
        apiClient: mockApiClient,
      });

      expect(result.success).toBe(true);
      if (!result.success) return;

      expect(result.data.conversation).toHaveLength(1);
      const turn = result.data.conversation[0];
      expect(turn.toolCalls).toHaveLength(1);
      expect(turn.toolCalls?.[0]).toMatchObject({
        toolCallId: "call-1",
        toolName: "ReadFile",
        input: { path: "/test.ts" },
      });
      expect(turn.toolCalls?.[0].result).toBeUndefined();
    });

    it("handles multiple orphaned tool calls", async () => {
      (mockApiClient.getTaskRun as ReturnType<typeof vi.fn>).mockResolvedValue(
        createTaskRun(),
      );
      (
        mockApiClient.fetchTaskRunLogs as ReturnType<typeof vi.fn>
      ).mockResolvedValue([
        createToolCall("call-1", "ReadFile", { path: "/a.ts" }),
        createToolResult("call-1", "content a"),
        createToolCall("call-2", "WriteFile", {
          path: "/b.ts",
          content: "new",
        }),
      ]);

      const saga = new ResumeSaga(mockLogger);
      const result = await saga.run({
        taskId: "task-1",
        runId: "run-1",
        repositoryPath: repo.path,
        apiClient: mockApiClient,
      });

      expect(result.success).toBe(true);
      if (!result.success) return;

      const toolCalls = result.data.conversation[0].toolCalls ?? [];
      expect(toolCalls).toHaveLength(2);
      expect(toolCalls[0].result).toBe("content a");
      expect(toolCalls[1].result).toBeUndefined();
    });
  });

  describe("checkpoint finding", () => {
    it("finds latest git checkpoint", async () => {
      (mockApiClient.getTaskRun as ReturnType<typeof vi.fn>).mockResolvedValue(
        createTaskRun(),
      );
      (
        mockApiClient.fetchTaskRunLogs as ReturnType<typeof vi.fn>
      ).mockResolvedValue([
        createGitCheckpointNotification({
          checkpointId: "checkpoint-1",
          checkpointRef: "refs/posthog-code-checkpoint/checkpoint-1",
          head: "head-1",
        }),
        createUserMessage("continue"),
        createGitCheckpointNotification({
          checkpointId: "checkpoint-2",
          checkpointRef: "refs/posthog-code-checkpoint/checkpoint-2",
          head: "head-2",
        }),
      ]);

      const saga = new ResumeSaga(mockLogger);
      const result = await saga.run({
        taskId: "task-1",
        runId: "run-1",
        repositoryPath: repo.path,
        apiClient: mockApiClient,
      });

      expect(result.success).toBe(true);
      if (!result.success) return;

      expect(result.data.latestGitCheckpoint?.checkpointId).toBe(
        "checkpoint-2",
      );
    });

    it("does not mark resume as interrupted from checkpoint state", async () => {
      (mockApiClient.getTaskRun as ReturnType<typeof vi.fn>).mockResolvedValue(
        createTaskRun(),
      );
      (
        mockApiClient.fetchTaskRunLogs as ReturnType<typeof vi.fn>
      ).mockResolvedValue([
        createGitCheckpointNotification({
          checkpointId: "checkpoint-1",
          checkpointRef: "refs/posthog-code-checkpoint/checkpoint-1",
        }),
      ]);

      const saga = new ResumeSaga(mockLogger);
      const result = await saga.run({
        taskId: "task-1",
        runId: "run-1",
        repositoryPath: repo.path,
        apiClient: mockApiClient,
      });

      expect(result.success).toBe(true);
      if (!result.success) return;

      expect(result.data.interrupted).toBe(false);
    });
  });

  describe("device info", () => {
    it("extracts device info from log entries", async () => {
      (mockApiClient.getTaskRun as ReturnType<typeof vi.fn>).mockResolvedValue(
        createTaskRun(),
      );
      (
        mockApiClient.fetchTaskRunLogs as ReturnType<typeof vi.fn>
      ).mockResolvedValue([
        createGitCheckpointNotification({
          checkpointId: "checkpoint-1",
          checkpointRef: "refs/posthog-code-checkpoint/checkpoint-1",
          device: { type: "local" },
        }),
        createGitCheckpointNotification({
          checkpointId: "checkpoint-2",
          checkpointRef: "refs/posthog-code-checkpoint/checkpoint-2",
          device: { type: "cloud" },
        }),
      ]);

      const saga = new ResumeSaga(mockLogger);
      const result = await saga.run({
        taskId: "task-1",
        runId: "run-1",
        repositoryPath: repo.path,
        apiClient: mockApiClient,
      });

      expect(result.success).toBe(true);
      if (!result.success) return;

      expect(result.data.lastDevice).toEqual({ type: "cloud" });
    });
  });

  describe("failure handling", () => {
    it("fails when getTaskRun throws", async () => {
      (mockApiClient.getTaskRun as ReturnType<typeof vi.fn>).mockRejectedValue(
        new Error("API error"),
      );

      const saga = new ResumeSaga(mockLogger);
      const result = await saga.run({
        taskId: "task-1",
        runId: "run-1",
        repositoryPath: repo.path,
        apiClient: mockApiClient,
      });

      expect(result.success).toBe(false);
      if (!result.success) {
        expect(result.error).toContain("API error");
      }
    });

    it("fails when fetchTaskRunLogs throws", async () => {
      (mockApiClient.getTaskRun as ReturnType<typeof vi.fn>).mockResolvedValue(
        createTaskRun(),
      );
      (
        mockApiClient.fetchTaskRunLogs as ReturnType<typeof vi.fn>
      ).mockRejectedValue(new Error("Log fetch failed"));

      const saga = new ResumeSaga(mockLogger);
      const result = await saga.run({
        taskId: "task-1",
        runId: "run-1",
        repositoryPath: repo.path,
        apiClient: mockApiClient,
      });

      expect(result.success).toBe(false);
      if (!result.success) {
        expect(result.error).toContain("Log fetch failed");
      }
    });
  });

  describe("session id", () => {
    const runStarted = (sessionId: string) =>
      createNotification(POSTHOG_NOTIFICATIONS.RUN_STARTED, { sessionId });
    const sdkPrefixedRunStarted = (sessionId: string) =>
      createNotification(`_${POSTHOG_NOTIFICATIONS.RUN_STARTED}`, {
        sessionId,
      });

    it.each([
      {
        name: "extracts the session id from the run_started notification",
        entries: () => [
          runStarted("session-abc"),
          createUserMessage("Hello"),
          createAgentChunk("Hi"),
        ],
        expected: "session-abc",
      },
      {
        name: "reads the sdk-prefixed run_started method too",
        entries: () => [
          sdkPrefixedRunStarted("session-prefixed"),
          createUserMessage("Hello"),
        ],
        expected: "session-prefixed",
      },
      {
        name: "returns the most recent session id when several are present",
        entries: () => [
          runStarted("session-old"),
          createUserMessage("Hello"),
          runStarted("session-new"),
        ],
        expected: "session-new",
      },
      {
        name: "returns null when no run_started notification is present",
        entries: () => [createUserMessage("Hello"), createAgentChunk("Hi")],
        expected: null,
      },
    ])("$name", async ({ entries, expected }) => {
      (mockApiClient.getTaskRun as ReturnType<typeof vi.fn>).mockResolvedValue(
        createTaskRun(),
      );
      (
        mockApiClient.fetchTaskRunLogs as ReturnType<typeof vi.fn>
      ).mockResolvedValue(entries());

      const saga = new ResumeSaga(mockLogger);
      const result = await saga.run({
        taskId: "task-1",
        runId: "run-1",
        repositoryPath: repo.path,
        apiClient: mockApiClient,
      });

      expect(result.success).toBe(true);
      if (!result.success) return;
      expect(result.data.sessionId).toBe(expected);
    });
  });

  describe("Codex goal state", () => {
    it.each([
      {
        name: "restores the latest persisted goal",
        entries: [
          createNotification(POSTHOG_NOTIFICATIONS.CODEX_GOAL, {
            goal: { objective: "Old goal", status: "active" },
          }),
          createNotification(`_${POSTHOG_NOTIFICATIONS.CODEX_GOAL}`, {
            goal: { objective: "Ship the fix", status: "paused" },
          }),
        ],
        expected: { objective: "Ship the fix", status: "paused" },
      },
      {
        name: "preserves an explicit goal clear",
        entries: [
          createNotification(POSTHOG_NOTIFICATIONS.CODEX_GOAL, {
            goal: { objective: "Ship the fix", status: "active" },
          }),
          createNotification(POSTHOG_NOTIFICATIONS.CODEX_GOAL, { goal: null }),
        ],
        expected: null,
      },
      {
        name: "skips malformed newer goal notifications",
        entries: [
          createNotification(POSTHOG_NOTIFICATIONS.CODEX_GOAL, {
            goal: { objective: "Ship the fix", status: "paused" },
          }),
          createNotification(POSTHOG_NOTIFICATIONS.CODEX_GOAL, {
            goal: { objective: "Invalid goal", status: "unknown" },
          }),
          createNotification(POSTHOG_NOTIFICATIONS.CODEX_GOAL, {}),
        ],
        expected: { objective: "Ship the fix", status: "paused" },
      },
      {
        name: "leaves goal state undefined when no notification exists",
        entries: [createUserMessage("Hello")],
        expected: undefined,
      },
    ])("$name", async ({ entries, expected }) => {
      (mockApiClient.getTaskRun as ReturnType<typeof vi.fn>).mockResolvedValue(
        createTaskRun(),
      );
      (
        mockApiClient.fetchTaskRunLogs as ReturnType<typeof vi.fn>
      ).mockResolvedValue(entries);

      const result = await new ResumeSaga(mockLogger).run({
        taskId: "task-1",
        runId: "run-1",
        repositoryPath: repo.path,
        apiClient: mockApiClient,
      });

      expect(result.success).toBe(true);
      if (!result.success) return;
      expect(result.data.nativeGoal).toEqual(expected);
    });
  });

  describe("log entry count", () => {
    it("reports correct log entry count", async () => {
      (mockApiClient.getTaskRun as ReturnType<typeof vi.fn>).mockResolvedValue(
        createTaskRun(),
      );
      (
        mockApiClient.fetchTaskRunLogs as ReturnType<typeof vi.fn>
      ).mockResolvedValue([
        createUserMessage("one"),
        createAgentChunk("two"),
        createUserMessage("three"),
      ]);

      const saga = new ResumeSaga(mockLogger);
      const result = await saga.run({
        taskId: "task-1",
        runId: "run-1",
        repositoryPath: repo.path,
        apiClient: mockApiClient,
      });

      expect(result.success).toBe(true);
      if (result.success) {
        expect(result.data.logEntryCount).toBe(3);
      }
    });
  });
});
