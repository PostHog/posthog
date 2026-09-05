import { ContainerModule } from "inversify";
import { AuthService } from "./auth";
import { AUTH_PREVIEW_DEPLOYMENT } from "./identifiers";

export const AUTH_SERVICE = Symbol.for("posthog.core.auth.service");

export const authCoreModule = new ContainerModule(({ bind }) => {
  // Ordinary builds (and any host that offers no preview selection) see null;
  // a preview host rebinds this to its validated manifest.
  bind(AUTH_PREVIEW_DEPLOYMENT).toConstantValue(null);
  bind(AuthService).toSelf().inSingletonScope();
  bind(AUTH_SERVICE).toService(AuthService);
});
