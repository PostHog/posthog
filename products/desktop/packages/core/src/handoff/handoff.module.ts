import { ContainerModule } from "inversify";
import { HandoffService } from "./handoff";
import { HANDOFF_SERVICE } from "./identifiers";

export const handoffModule = new ContainerModule(({ bind }) => {
  bind(HANDOFF_SERVICE).to(HandoffService).inSingletonScope();
});
