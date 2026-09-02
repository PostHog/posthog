import { container } from "../di/container";
import {
  DEV_FLAGS_SERVICE,
  DEV_LOGS_SERVICE,
  DEV_NETWORK_SERVICE,
} from "../di/tokens";
import { DevFlagsEvent } from "./dev-flags/schemas";
import type { DevFlagsService } from "./dev-flags/service";
import type { DevLogsService } from "./dev-logs/service";
import type { DevNetworkService } from "./dev-network/service";

export function initDevToolbar(): void {
  const flags = container.get<DevFlagsService>(DEV_FLAGS_SERVICE);
  const network = container.get<DevNetworkService>(DEV_NETWORK_SERVICE);
  const logs = container.get<DevLogsService>(DEV_LOGS_SERVICE);

  const installCapture = () => {
    network.install();
    logs.install();
  };

  const uninstallCapture = () => {
    network.uninstall();
    logs.uninstall();
  };

  if (flags.getFlags().devMode) installCapture();

  flags.on(DevFlagsEvent.Changed, (next) => {
    if (next.devMode) {
      installCapture();
    } else {
      uninstallCapture();
    }
  });
}
