import { ROOT_LOGGER, type RootLogger } from "@posthog/di/logger";
import {
  ANALYTICS_SERVICE,
  type IAnalytics,
} from "@posthog/platform/analytics";
import {
  type IPowerManager,
  POWER_MANAGER_SERVICE,
} from "@posthog/platform/power-manager";
import { inject, injectable, optional, preDestroy } from "inversify";
import { CloudTaskEngine } from "./cloud-task-engine";
import {
  CLOUD_TASK_AUTH,
  type ICloudTaskAuth,
  MCP_RELAY_EXECUTOR,
  type McpRelayExecutor,
} from "./identifiers";

@injectable()
export class CloudTaskService extends CloudTaskEngine {
  private readonly disposeResumeListener: (() => void) | null;

  constructor(
    @inject(CLOUD_TASK_AUTH)
    auth: ICloudTaskAuth,
    @inject(ANALYTICS_SERVICE)
    analytics: IAnalytics,
    @inject(ROOT_LOGGER)
    logger: RootLogger,
    @inject(MCP_RELAY_EXECUTOR)
    @optional()
    mcpRelayExecutor: McpRelayExecutor | null = null,
    @inject(POWER_MANAGER_SERVICE)
    @optional()
    powerManager: IPowerManager | null = null,
  ) {
    super({ auth, analytics, logger, mcpRelayExecutor });
    // Sleep kills the SSE sockets without an error or EOF, so without this
    // nudge a wake waits out the full idle timeout before reconnecting.
    this.disposeResumeListener =
      powerManager?.onResume(() => this.reconnectAllIfDisconnected()) ?? null;
  }

  @preDestroy()
  override unwatchAll(): void {
    this.disposeResumeListener?.();
    super.unwatchAll();
  }
}
