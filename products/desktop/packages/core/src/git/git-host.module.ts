import { ContainerModule } from "inversify";
import { GitHostService } from "./git-host";
import { GIT_SERVICE } from "./identifiers";

export const gitHostModule = new ContainerModule(({ bind }) => {
  bind(GitHostService).toSelf().inSingletonScope();
  bind(GIT_SERVICE).toService(GitHostService);
});
