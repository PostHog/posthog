import type {
  ExtensionAPI,
  SessionEntry,
  SessionManager,
} from "@earendil-works/pi-coding-agent";
import { describe, expect, it, vi } from "vitest";
import { buildTaskSystemPrompt, type TaskContext } from "./task-system-prompt";
import {
  createPiTaskSystemPromptExtension,
  POSTHOG_PI_TASK_CONTEXT_ENTRY_TYPE,
  resolvePiTaskContext,
} from "./task-system-prompt-extension";

const taskContext: TaskContext = {
  projectId: 42,
  apiHost: "https://us.posthog.com",
  taskId: "task-123",
  cwd: "/tmp/task-123",
  environment: "local",
};

describe("Pi task system prompt", () => {
  it("persists a new context and restores it on resume", () => {
    const appendCustomEntry = vi.fn();
    const manager = {
      getEntries: () => [],
      appendCustomEntry,
    } as unknown as SessionManager;

    expect(resolvePiTaskContext(manager, undefined)).toBeNull();
    expect(resolvePiTaskContext(manager, taskContext)).toEqual(taskContext);
    expect(appendCustomEntry).toHaveBeenCalledWith(
      POSTHOG_PI_TASK_CONTEXT_ENTRY_TYPE,
      { context: taskContext },
    );

    const persistedManager = {
      getEntries: () =>
        [
          {
            type: "custom",
            customType: POSTHOG_PI_TASK_CONTEXT_ENTRY_TYPE,
            data: { context: taskContext },
          },
        ] as SessionEntry[],
    } as unknown as SessionManager;
    expect(resolvePiTaskContext(persistedManager, undefined)).toEqual(
      taskContext,
    );
  });

  it("preserves optional persisted context when resume supplies runtime fields", () => {
    const persistedContext: TaskContext = {
      ...taskContext,
      customInstructions: "Keep the patch small.",
      additionalDirectories: ["/tmp/shared"],
      channelMode: true,
    };
    const appendCustomEntry = vi.fn();
    const manager = {
      getEntries: () =>
        [
          {
            type: "custom",
            customType: POSTHOG_PI_TASK_CONTEXT_ENTRY_TYPE,
            data: { context: persistedContext },
          },
        ] as SessionEntry[],
      appendCustomEntry,
    } as unknown as SessionManager;

    expect(resolvePiTaskContext(manager, taskContext)).toEqual(
      persistedContext,
    );
    expect(appendCustomEntry).not.toHaveBeenCalled();
  });

  it("renders and appends the task prompt before each agent run", () => {
    const handlers = new Map<string, unknown>();
    createPiTaskSystemPromptExtension(taskContext).factory({
      on: (event: string, handler: unknown) => handlers.set(event, handler),
    } as unknown as ExtensionAPI);
    const beforeAgentStart = handlers.get("before_agent_start") as (event: {
      systemPrompt: string;
    }) => { systemPrompt: string };

    expect(beforeAgentStart({ systemPrompt: "Pi instructions" })).toEqual({
      systemPrompt: `Pi instructions\n\n${buildTaskSystemPrompt(taskContext)}`,
    });
  });
});
