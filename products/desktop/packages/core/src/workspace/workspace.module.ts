import { ContainerModule } from "inversify";
import { WORKSPACE_SETUP_SERVICE } from "./identifiers";
import { WorkspaceSetupService } from "./WorkspaceSetupService";

export const workspaceModule = new ContainerModule(({ bind }) => {
  bind(WORKSPACE_SETUP_SERVICE).to(WorkspaceSetupService).inSingletonScope();
});
