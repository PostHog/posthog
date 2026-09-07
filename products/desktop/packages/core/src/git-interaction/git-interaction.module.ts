import { ContainerModule } from "inversify";
import { GitInteractionService } from "./gitInteractionService";
import { GIT_INTERACTION_SERVICE } from "./identifiers";

export const gitInteractionModule = new ContainerModule(({ bind }) => {
  bind(GIT_INTERACTION_SERVICE).to(GitInteractionService).inSingletonScope();
});
