import type {
  AppProcessMetric,
  IAppMetrics,
} from "@posthog/platform/app-metrics";
import { app } from "electron";
import { injectable } from "inversify";

@injectable()
export class ElectronAppMetrics implements IAppMetrics {
  public getAppMetrics(): AppProcessMetric[] {
    return app.getAppMetrics().map((m) => ({
      pid: m.pid,
      type: m.type,
      name: m.name,
      cpu: m.cpu ? { percentCPUUsage: m.cpu.percentCPUUsage } : undefined,
      memory: m.memory
        ? { workingSetSize: m.memory.workingSetSize }
        : undefined,
    }));
  }
}
