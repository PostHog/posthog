import { ContainerModule } from "inversify";
import { EmbeddedBrowserService } from "./embeddedBrowser";
import { EMBEDDED_BROWSER_SERVICE } from "./identifiers";

export const embeddedBrowserCoreModule = new ContainerModule(({ bind }) => {
  bind(EMBEDDED_BROWSER_SERVICE).to(EmbeddedBrowserService).inSingletonScope();
});
