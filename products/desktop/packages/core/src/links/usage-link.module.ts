import { ContainerModule } from "inversify";
import { USAGE_LINK_SERVICE } from "./identifiers";
import { UsageLinkService } from "./usage-link";

export const usageLinkModule = new ContainerModule(({ bind }) => {
  bind(USAGE_LINK_SERVICE).to(UsageLinkService).inSingletonScope();
});
