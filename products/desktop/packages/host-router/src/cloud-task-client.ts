import type { CloudTaskClient } from "@posthog/core/cloud-task/cloudTaskClient";
import type { SendCommandInput } from "@posthog/core/cloud-task/schemas";
import { SharedCloudTaskSubscriptions } from "@posthog/core/cloud-task/sharedCloudTaskSubscriptions";
import type { CloudTaskUpdatePayload } from "@posthog/shared/domain-types";
import { inject, injectable } from "inversify";
import { HOST_TRPC_CLIENT, type HostTrpcClient } from "./client";

@injectable()
export class TrpcCloudTaskClient implements CloudTaskClient {
  private readonly subscriptions: SharedCloudTaskSubscriptions;

  constructor(
    @inject(HOST_TRPC_CLIENT) private readonly client: HostTrpcClient,
  ) {
    this.subscriptions = new SharedCloudTaskSubscriptions({
      subscribe: (taskId, runId, handlers) => {
        const subscription = this.client.cloudTask.onUpdate.subscribe(
          { taskId, runId },
          {
            onData: handlers.onUpdate,
            onError: handlers.onError,
            onStarted: handlers.onStarted,
            onComplete: handlers.onComplete,
          },
        );
        return () => subscription.unsubscribe();
      },
      unwatch: (taskId, runId) => this.unwatch(taskId, runId),
    });
  }

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
    return this.subscriptions.subscribe(taskId, runId, {
      onUpdate,
      onError,
      onStarted,
    });
  }

  sendCommand(input: SendCommandInput) {
    return this.client.cloudTask.sendCommand.mutate(input);
  }
}
