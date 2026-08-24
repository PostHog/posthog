import type { PlanEntry } from "@agentclientprotocol/sdk";
import type { SessionMessage } from "@anthropic-ai/claude-agent-sdk";
import type {
  TaskCreateInput,
  TaskCreateOutput,
  TaskUpdateInput,
} from "@anthropic-ai/claude-agent-sdk/sdk-tools.js";

export type TaskEntry = {
  subject: string;
  status: "pending" | "in_progress" | "completed";
  activeForm?: string;
  description?: string;
};

export type TaskState = Map<string, TaskEntry>;

export function parseTaskCreateOutput(
  content: unknown,
): TaskCreateOutput | undefined {
  const tryParse = (text: string): TaskCreateOutput | undefined => {
    try {
      const parsed = JSON.parse(text);
      if (
        parsed &&
        typeof parsed === "object" &&
        parsed.task &&
        typeof parsed.task.id === "string"
      ) {
        return parsed as TaskCreateOutput;
      }
    } catch {
      // ignore
    }
    return undefined;
  };

  if (typeof content === "string") {
    return tryParse(content);
  }
  if (Array.isArray(content)) {
    for (const block of content) {
      if (
        block &&
        typeof block === "object" &&
        "type" in block &&
        block.type === "text"
      ) {
        const text = (block as { text?: unknown }).text;
        if (typeof text === "string") {
          const parsed = tryParse(text);
          if (parsed) return parsed;
        }
      }
    }
  }
  return undefined;
}

export function applyTaskCreate(
  state: TaskState,
  input: TaskCreateInput | undefined,
  output: TaskCreateOutput | undefined,
): void {
  const taskId = output?.task?.id;
  if (!taskId || !input) return;
  state.set(taskId, {
    subject: input.subject,
    status: "pending",
    activeForm: input.activeForm,
    description: input.description,
  });
}

export function applyTaskUpdate(
  state: TaskState,
  input: TaskUpdateInput | undefined,
): void {
  if (!input?.taskId) return;
  if (input.status === "deleted") {
    state.delete(input.taskId);
    return;
  }
  const existing = state.get(input.taskId);
  const subject = input.subject ?? existing?.subject;
  if (!subject) return;
  state.set(input.taskId, {
    subject,
    status: input.status ?? existing?.status ?? "pending",
    activeForm: input.activeForm ?? existing?.activeForm,
    description: input.description ?? existing?.description,
  });
}

export function taskStateToPlanEntries(state: TaskState): PlanEntry[] {
  return Array.from(state.values()).map((task) => ({
    content: task.subject,
    status: task.status,
    priority: "medium",
  }));
}

type ToolUseBlock = {
  type: "tool_use";
  id: string;
  name: string;
  input?: unknown;
};

type ToolResultBlock = {
  type: "tool_result";
  tool_use_id: string;
  content?: unknown;
  is_error?: boolean;
};

function isToolUseBlock(block: unknown): block is ToolUseBlock {
  return (
    !!block &&
    typeof block === "object" &&
    (block as { type?: unknown }).type === "tool_use" &&
    typeof (block as { id?: unknown }).id === "string" &&
    typeof (block as { name?: unknown }).name === "string"
  );
}

function isToolResultBlock(block: unknown): block is ToolResultBlock {
  return (
    !!block &&
    typeof block === "object" &&
    (block as { type?: unknown }).type === "tool_result" &&
    typeof (block as { tool_use_id?: unknown }).tool_use_id === "string"
  );
}

/**
 * Rebuild `state` from a JSONL message transcript by replaying Task tool
 * inputs/outputs. Used by `resumeSession` to recover the plan panel when the
 * agent restarts mid-conversation; `loadSession` covers the same ground via
 * the full notification replay in `replaySessionHistory`.
 */
export function rehydrateTaskState(
  messages: ReadonlyArray<SessionMessage>,
  state: TaskState,
): void {
  const pendingInputs = new Map<string, { name: string; input: unknown }>();
  for (const msg of messages) {
    const content = (msg.message as { content?: unknown } | null | undefined)
      ?.content;
    if (!Array.isArray(content)) continue;
    if (msg.type === "assistant") {
      for (const block of content) {
        if (
          isToolUseBlock(block) &&
          (block.name === "TaskCreate" || block.name === "TaskUpdate")
        ) {
          pendingInputs.set(block.id, { name: block.name, input: block.input });
        }
      }
    } else if (msg.type === "user") {
      for (const block of content) {
        if (!isToolResultBlock(block) || block.is_error) continue;
        const cached = pendingInputs.get(block.tool_use_id);
        if (!cached) continue;
        if (cached.name === "TaskCreate") {
          applyTaskCreate(
            state,
            cached.input as TaskCreateInput | undefined,
            parseTaskCreateOutput(block.content),
          );
        } else if (cached.name === "TaskUpdate") {
          applyTaskUpdate(state, cached.input as TaskUpdateInput | undefined);
        }
        pendingInputs.delete(block.tool_use_id);
      }
    }
  }
}
