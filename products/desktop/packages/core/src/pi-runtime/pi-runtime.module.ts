import { ContainerModule } from "inversify";
import { PI_SESSION_CONTROLLER } from "./identifiers";
import { PiSessionController } from "./piSessionController";

export const piRuntimeModule = new ContainerModule(({ bind }) => {
  bind(PI_SESSION_CONTROLLER).to(PiSessionController).inSingletonScope();
});
