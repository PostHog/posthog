import { ROOT_LOGGER, type RootLogger } from "@posthog/di/logger";
import {
  ANALYTICS_SERVICE,
  type IAnalytics,
} from "@posthog/platform/analytics";
import { TRANSCRIPT_TAIL_WINDOW } from "@posthog/shared";
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
  ) {
    // The desktop renderer pages older history in from `windowStart`.
    super({
      auth,
      analytics,
      logger,
      mcpRelayExecutor,
      transcriptTailWindow: TRANSCRIPT_TAIL_WINDOW,
    });
  }

  @preDestroy()
  override unwatchAll(): void {
    super.unwatchAll();
  }
}
