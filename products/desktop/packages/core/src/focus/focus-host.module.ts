import { ContainerModule } from "inversify";
import { FocusHostService } from "./focus-service";
import { FOCUS_SERVICE } from "./identifiers";

export const focusHostModule = new ContainerModule(({ bind }) => {
  bind(FocusHostService).toSelf().inSingletonScope();
  bind(FOCUS_SERVICE).toService(FocusHostService);
});
