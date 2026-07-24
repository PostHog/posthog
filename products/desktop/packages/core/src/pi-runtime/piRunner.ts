export interface PiRunInput {
  taskId: string;
  cwd: string;
  prompt: string;
  model?: string;
}

export interface PiResumeInput {
  taskId: string;
  cwd: string;
}

export interface PiRunner {
  create(input: PiRunInput): Promise<void>;
  resume(input: PiResumeInput): Promise<void>;
  stop(taskId: string): Promise<void>;
}
