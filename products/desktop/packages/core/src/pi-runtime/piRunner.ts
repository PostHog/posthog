import type { PiThinkingLevel } from "@posthog/agent/pi/types";
import type { TaskContextInput } from "@posthog/shared/task-context";

export interface PiRunInput {
  taskContext: TaskContextInput;
  prompt: string;
  model?: string;
  thinkingLevel?: PiThinkingLevel;
}

export interface PiResumeInput {
  taskContext: Pick<TaskContextInput, "taskId" | "cwd">;
}

export interface PiRunner {
  create(input: PiRunInput): Promise<void>;
  resume(input: PiResumeInput): Promise<void>;
  stop(taskId: string): Promise<void>;
}
