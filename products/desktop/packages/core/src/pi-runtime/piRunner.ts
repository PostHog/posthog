import type { TaskContextInput } from "@posthog/agent/pi/task-system-prompt";
import type { PiThinkingLevel } from "@posthog/agent/pi/types";
import type { PiSubscriptionProvider } from "@posthog/shared";

export interface PiRunInput {
  taskContext: TaskContextInput;
  prompt: string;
  model?: string;
  thinkingLevel?: PiThinkingLevel;
  piSubscriptionProvider?: PiSubscriptionProvider;
}

export interface PiResumeInput {
  taskContext: Pick<TaskContextInput, "taskId" | "cwd">;
}

export interface PiRunner {
  create(input: PiRunInput): Promise<void>;
  resume(input: PiResumeInput): Promise<void>;
  stop(taskId: string): Promise<void>;
}
