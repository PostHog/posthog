import { TASK_BROWSER_MCP_SERVER } from "@posthog/shared/constants";
import { BrowserMcpHandler, BrowserMcpHttpServer } from "./mcp";
import { BrowserRunner } from "./runner";
import type { TaskBrowserService } from "./service";

type RelayExecution = {
  payload?: Record<string, unknown>;
  error?: { code: number; message: string };
};

export interface RelayExecutor {
  execute(
    runId: string,
    server: string,
    payload: Record<string, unknown>,
    taskId?: string,
  ): Promise<RelayExecution>;
  closeRun?(runId: string): Promise<void>;
}

export class TaskBrowserHost {
  private readonly handler: BrowserMcpHandler;
  private readonly http: BrowserMcpHttpServer;

  constructor(service: TaskBrowserService) {
    this.handler = new BrowserMcpHandler(new BrowserRunner(service));
    this.http = new BrowserMcpHttpServer(this.handler);
  }

  localConnection(taskId: string): Promise<{ url: string; token: string }> {
    return this.http.connectionFor(taskId);
  }

  relayExecutor(fallback: RelayExecutor): RelayExecutor {
    return {
      execute: async (runId, server, payload, taskId) => {
        if (server !== TASK_BROWSER_MCP_SERVER) {
          return fallback.execute(runId, server, payload, taskId);
        }
        if (!taskId) {
          return {
            error: { code: -32000, message: "Unknown task for the browser." },
          };
        }
        const response = await this.handler.handle(taskId, payload);
        return response ? { payload: response } : {};
      },
      closeRun: (runId) => fallback.closeRun?.(runId) ?? Promise.resolve(),
    };
  }
}
