import { ContainerModule } from "inversify";
import { AuthService } from "./auth";

export const AUTH_SERVICE = Symbol.for("posthog.core.auth.service");

export const authCoreModule = new ContainerModule(({ bind }) => {
  bind(AuthService).toSelf().inSingletonScope();
  bind(AUTH_SERVICE).toService(AuthService);
});
