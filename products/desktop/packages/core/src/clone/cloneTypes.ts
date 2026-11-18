export type CloneStatus = "cloning" | "complete" | "error";

export interface CloneProgressEvent {
  cloneId: string;
  status: CloneStatus;
  message: string;
}

export interface CloneOperation {
  cloneId: string;
  repository: string;
  targetPath: string;
  status: CloneStatus;
  latestMessage?: string;
  error?: string;
}
