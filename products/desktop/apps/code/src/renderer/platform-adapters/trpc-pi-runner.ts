import type {
  PiResumeInput,
  PiRunInput,
  PiRunner,
} from "@posthog/core/pi-runtime/piRunner";
import {
  HOST_TRPC_CLIENT,
  type HostTrpcClient,
} from "@posthog/host-router/client";
import { inject, injectable } from "inversify";

@injectable()
export class TrpcPiRunner implements PiRunner {
  constructor(
    @inject(HOST_TRPC_CLIENT) private readonly hostClient: HostTrpcClient,
  ) {}

  async create(input: PiRunInput): Promise<void> {
    await this.hostClient.piSession.start.mutate(input);
  }

  resume(input: PiResumeInput): Promise<void> {
    return this.hostClient.piSession.resume.mutate(input);
  }

  stop(taskId: string): Promise<void> {
    return this.hostClient.piSession.stop.mutate({ taskId });
  }
}
