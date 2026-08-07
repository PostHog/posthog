import type { Contribution } from "@posthog/di/contribution";
import {
  HOST_TRPC_CLIENT,
  type HostTrpcClient,
} from "@posthog/host-router/client";
import { inject, injectable } from "inversify";
import { useProvisioningStore } from "./store";

@injectable()
export class ProvisioningContribution implements Contribution {
  constructor(
    @inject(HOST_TRPC_CLIENT)
    private readonly hostClient: HostTrpcClient,
  ) {}

  start(): void {
    this.hostClient.provisioning.onOutput.subscribe(undefined, {
      onData: ({ taskId, data }) => {
        useProvisioningStore.getState().appendChunk(taskId, data);
      },
    });
  }
}
