import type { CloudTaskUpdatePayload } from "@posthog/shared/domain-types";
import type { SendCommandInput, SendCommandOutput } from "./schemas";

export const CLOUD_TASK_CLIENT = Symbol.for("posthog.cloudTask.client");

export interface CloudTaskClient {
  getContext(): Promise<{ apiHost: string; teamId: number } | null>;
  watch(input: {
    taskId: string;
    runId: string;
    apiHost: string;
    teamId: number;
  }): Promise<void>;
  unwatch(taskId: string, runId: string): Promise<void>;
  retry(taskId: string, runId: string): Promise<void>;
  subscribe(
    taskId: string,
    runId: string,
    onUpdate: (update: CloudTaskUpdatePayload) => void,
    onError: (error: unknown) => void,
    onStarted: () => void,
  ): () => void;
  sendCommand(input: SendCommandInput): Promise<SendCommandOutput>;
}
