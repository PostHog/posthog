import { ContainerModule } from "inversify";
import { MCP_APPS_SERVICE } from "./identifiers";
import { McpAppsService } from "./mcp-apps";

export const mcpAppsModule = new ContainerModule(({ bind }) => {
  bind(MCP_APPS_SERVICE).to(McpAppsService).inSingletonScope();
});
