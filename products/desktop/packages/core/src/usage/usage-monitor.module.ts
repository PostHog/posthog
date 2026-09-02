import { ContainerModule } from "inversify";
import { USAGE_MONITOR_SERVICE } from "./identifiers";
import { UsageMonitorService } from "./usage-monitor";

export const usageMonitorModule = new ContainerModule(({ bind }) => {
  bind(USAGE_MONITOR_SERVICE).to(UsageMonitorService).inSingletonScope();
});
