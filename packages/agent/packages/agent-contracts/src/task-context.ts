export interface TaskContextInput {
  taskId: string;
  cwd: string;
  customInstructions?: string;
  additionalDirectories?: string[];
  channelMode?: boolean;
}

export interface TaskContext extends TaskContextInput {
  projectId: number;
  apiHost: string;
  environment: "local" | "cloud";
  additionalInstructions?: string;
}
