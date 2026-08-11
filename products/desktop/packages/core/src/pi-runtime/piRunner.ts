import type { PiThinkingLevel } from "@posthog/agent/pi/types";

export interface PiRunInput {
  taskId: string;
  cwd: string;
  projectTrustPath?: string;
  prompt: string;
  model?: string;
  thinkingLevel?: PiThinkingLevel;
}

export interface PiResumeInput {
  taskId: string;
  cwd: string;
  projectTrustPath?: string;
}

export interface PiRunner {
  create(input: PiRunInput): Promise<void>;
  resume(input: PiResumeInput): Promise<void>;
  stop(taskId: string): Promise<void>;
}
