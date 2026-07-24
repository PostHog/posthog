import { ContainerModule } from "inversify";
import { LOCAL_MCP_IMPORT_SERVICE } from "./identifiers";
import { LocalMcpImportService } from "./localMcpImport";

export const localMcpCoreModule = new ContainerModule(({ bind }) => {
  bind(LOCAL_MCP_IMPORT_SERVICE).to(LocalMcpImportService).inSingletonScope();
});
