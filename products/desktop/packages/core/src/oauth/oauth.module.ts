import { ContainerModule } from "inversify";
import { OAUTH_SERVICE } from "./identifiers";
import { OAuthService } from "./oauth";

export const oauthModule = new ContainerModule(({ bind }) => {
  bind(OAUTH_SERVICE).to(OAuthService).inSingletonScope();
});
