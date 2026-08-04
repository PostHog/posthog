import { PiRuntime } from "@posthog/agent/pi/runtime";
import {
  PI_RPC_CLIENT_FACTORY,
  type PiRpcClientFactory,
  type PiRuntimeFactory,
} from "@posthog/workspace-server/services/pi-session/identifiers";
import { inject, injectable } from "inversify";

@injectable()
export class DesktopPiRuntimeFactory implements PiRuntimeFactory {
  constructor(
    @inject(PI_RPC_CLIENT_FACTORY)
    private readonly clientFactory: PiRpcClientFactory,
  ) {}

  async create(input: {
    cwd: string;
    model?: string;
    sessionFile?: string;
  }): Promise<PiRuntime> {
    const client = await this.clientFactory.create(input);
    return new PiRuntime(client);
  }
}
