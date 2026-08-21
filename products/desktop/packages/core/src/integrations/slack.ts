import {
  ROOT_LOGGER,
  type RootLogger,
  type ScopedLogger,
} from "@posthog/di/logger";
import {
  DEEP_LINK_SERVICE,
  type IDeepLinkRegistry,
} from "@posthog/platform/deep-link";
import {
  type IMainWindow,
  MAIN_WINDOW_SERVICE,
} from "@posthog/platform/main-window";
import {
  type IUrlLauncher,
  URL_LAUNCHER_SERVICE,
} from "@posthog/platform/url-launcher";
import {
  type CloudRegion,
  getCloudUrlFromRegion,
  TypedEventEmitter,
} from "@posthog/shared";
import { inject, injectable } from "inversify";
import type { StartIntegrationFlowOutput } from "./schemas";

const FLOW_TIMEOUT_MS = 5 * 60 * 1000;

export const SlackIntegrationEvent = {
  Callback: "callback",
  FlowTimedOut: "flowTimedOut",
} as const;

export interface SlackIntegrationCallback {
  projectId: number | null;
  integrationId: number | null;
  status: "success" | "error";
  errorCode: string | null;
  errorMessage: string | null;
}

export interface SlackFlowTimedOut {
  projectId: number;
}

export interface SlackIntegrationEvents {
  [SlackIntegrationEvent.Callback]: SlackIntegrationCallback;
  [SlackIntegrationEvent.FlowTimedOut]: SlackFlowTimedOut;
}

@injectable()
export class SlackIntegrationService extends TypedEventEmitter<SlackIntegrationEvents> {
  private pendingCallback: SlackIntegrationCallback | null = null;
  private flowTimeout: ReturnType<typeof setTimeout> | null = null;
  private readonly log: ScopedLogger;

  constructor(
    @inject(DEEP_LINK_SERVICE)
    private readonly deepLinkService: IDeepLinkRegistry,
    @inject(URL_LAUNCHER_SERVICE)
    private readonly urlLauncher: IUrlLauncher,
    @inject(MAIN_WINDOW_SERVICE)
    private readonly mainWindow: IMainWindow,
    @inject(ROOT_LOGGER)
    rootLogger: RootLogger,
  ) {
    super();

    this.log = rootLogger.scope("slack-integration-service");

    this.deepLinkService.registerHandler("slack-integration", (_path, params) =>
      this.handleCallback(params),
    );
  }

  public async startFlow(
    region: CloudRegion,
    projectId: number,
  ): Promise<StartIntegrationFlowOutput> {
    try {
      const cloudUrl = getCloudUrlFromRegion(region);
      const nextPath = `/account-connected/slack-integration?provider=slack&project_id=${projectId}&connect_from=posthog_code`;
      const authorizeUrl = `${cloudUrl}/api/environments/${projectId}/integrations/authorize/?kind=slack&next=${encodeURIComponent(nextPath)}`;

      this.clearFlowTimeout();
      this.flowTimeout = setTimeout(() => {
        this.log.warn("Slack integration flow timed out", { projectId });
        this.flowTimeout = null;
        this.emit(SlackIntegrationEvent.FlowTimedOut, { projectId });
      }, FLOW_TIMEOUT_MS);

      await this.urlLauncher.launch(authorizeUrl);

      return { success: true };
    } catch (error) {
      this.clearFlowTimeout();
      this.log.error("Failed to start Slack integration flow", {
        projectId,
        error: error instanceof Error ? error.message : String(error),
      });
      return {
        success: false,
        error: error instanceof Error ? error.message : "Unknown error",
      };
    }
  }

  public consumePendingCallback(): SlackIntegrationCallback | null {
    const pending = this.pendingCallback;
    this.pendingCallback = null;
    return pending;
  }

  private handleCallback(params: URLSearchParams): boolean {
    const projectIdRaw = params.get("project_id");
    const parsedProjectId = projectIdRaw ? Number(projectIdRaw) : null;
    const integrationIdRaw = params.get("integration_id");
    const parsedIntegrationId = integrationIdRaw
      ? Number(integrationIdRaw)
      : null;
    const status = params.get("status") === "error" ? "error" : "success";

    const callback: SlackIntegrationCallback = {
      projectId:
        parsedProjectId !== null && Number.isFinite(parsedProjectId)
          ? parsedProjectId
          : null,
      integrationId:
        parsedIntegrationId !== null && Number.isFinite(parsedIntegrationId)
          ? parsedIntegrationId
          : null,
      status,
      errorCode: params.get("error_code") || null,
      errorMessage: params.get("error_message") || null,
    };

    this.clearFlowTimeout();

    if (status === "error") {
      this.log.error("Received Slack integration callback with error", {
        projectId: callback.projectId,
        errorCode: callback.errorCode,
        errorMessage: callback.errorMessage,
      });
    }

    const hasListeners = this.listenerCount(SlackIntegrationEvent.Callback) > 0;
    if (hasListeners) {
      this.emit(SlackIntegrationEvent.Callback, callback);
    } else {
      this.pendingCallback = callback;
    }

    if (this.mainWindow.isMinimized()) {
      this.mainWindow.restore();
    }
    this.mainWindow.focus();

    return true;
  }

  private clearFlowTimeout(): void {
    if (this.flowTimeout) {
      clearTimeout(this.flowTimeout);
      this.flowTimeout = null;
    }
  }
}
