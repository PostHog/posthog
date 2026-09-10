import { ContainerModule } from "inversify";
import { GitPrService } from "./git-pr";
import { GIT_PR_SERVICE } from "./identifiers";

export const gitPrModule = new ContainerModule(({ bind }) => {
  bind(GIT_PR_SERVICE).to(GitPrService).inSingletonScope();
});
