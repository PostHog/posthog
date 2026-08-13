import { ContainerModule } from "inversify";
import { HomeService } from "./homeService";
import { HOME_SERVICE } from "./identifiers";

// Home's prefetched groups of work. Host-agnostic: it needs only the shared
// ProjectApiClient (bound by canvasCoreModule), so any host can load it.
export const homeCoreModule = new ContainerModule(({ bind }) => {
  bind(HomeService).toSelf().inSingletonScope();
  bind(HOME_SERVICE).toService(HomeService);
});
