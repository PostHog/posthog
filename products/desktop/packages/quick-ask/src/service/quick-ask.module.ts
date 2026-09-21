import { ContainerModule } from "inversify";
import { QUICK_ASK_SERVICE, QuickAskService } from "./quick-ask";

export const quickAskCoreModule = new ContainerModule(({ bind }) => {
  bind(QuickAskService).toSelf().inSingletonScope();
  bind(QUICK_ASK_SERVICE).toService(QuickAskService);
});
