import type { CloudTaskClient } from "@posthog/core/cloud-task/cloudTaskClient";
import type { SendCommandInput } from "@posthog/core/cloud-task/schemas";
import type { CloudTaskUpdatePayload } from "@posthog/shared/domain-types";
import { inject, injectable } from "inversify";
import { HOST_TRPC_CLIENT, type HostTrpcClient } from "./client";

@injectable()
export class TrpcCloudTaskClient implements CloudTaskClient {
  constructor(
    @inject(HOST_TRPC_CLIENT) private readonly client: HostTrpcClient,
  ) {}

  getContext(): Promise<{ apiHost: string; teamId: number } | null> {
    return this.client.cloudTask.context.query();
  }

  async watch(input: {
    taskId: string;
    runId: string;
    apiHost: string;
    teamId: number;
  }): Promise<void> {
    await this.client.cloudTask.watch.mutate(input);
  }

  async unwatch(taskId: string, runId: string): Promise<void> {
    await this.client.cloudTask.unwatch.mutate({ taskId, runId });
  }

  async retry(taskId: string, runId: string): Promise<void> {
    await this.client.cloudTask.retry.mutate({ taskId, runId });
  }

  subscribe(
    taskId: string,
    runId: string,
    onUpdate: (update: CloudTaskUpdatePayload) => void,
    onError: (error: unknown) => void,
    onStarted: () => void,
  ): () => void {
    const subscription = this.client.cloudTask.onUpdate.subscribe(
      { taskId, runId },
      { onData: onUpdate, onError, onStarted },
    );
    return () => subscription.unsubscribe();
  }

  sendCommand(input: SendCommandInput) {
    return this.client.cloudTask.sendCommand.mutate(input);
  }
}
