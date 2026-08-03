import { ContainerModule } from "inversify";
import { PI_SESSION_CONTROLLER } from "./identifiers";
import {
  PI_SESSION_PROVIDER,
  PiSessionController,
} from "./piSessionController";
import { RoutingPiSessionProvider } from "./piSessionProvider";

export const piRuntimeModule = new ContainerModule(({ bind }) => {
  bind(PI_SESSION_PROVIDER).to(RoutingPiSessionProvider).inSingletonScope();
  bind(PI_SESSION_CONTROLLER).to(PiSessionController).inSingletonScope();
});
