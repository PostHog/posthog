import { TypedEventEmitter } from "@posthog/shared";
import { injectable } from "inversify";

export const ProvisioningEvent = {
  Output: "output",
} as const;

export interface ProvisioningOutputPayload {
  taskId: string;
  data: string;
}

export interface ProvisioningServiceEvents {
  [ProvisioningEvent.Output]: ProvisioningOutputPayload;
}

@injectable()
export class ProvisioningService extends TypedEventEmitter<ProvisioningServiceEvents> {
  emitOutput(taskId: string, data: string): void {
    this.emit(ProvisioningEvent.Output, { taskId, data });
  }
}
