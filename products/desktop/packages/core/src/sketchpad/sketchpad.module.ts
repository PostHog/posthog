import { ContainerModule } from "inversify";
import {
  SKETCHPAD_BOARDS_SERVICE,
  SKETCHPAD_STREAM_SERVICE,
} from "./identifiers";
import { SketchpadService } from "./sketchpadService";
import { SketchpadStreamService } from "./sketchpadStreamService";

export const sketchpadCoreModule = new ContainerModule(({ bind }) => {
  bind(SketchpadService).toSelf().inSingletonScope();
  bind(SKETCHPAD_BOARDS_SERVICE).toService(SketchpadService);
  bind(SketchpadStreamService).toSelf().inSingletonScope();
  bind(SKETCHPAD_STREAM_SERVICE).toService(SketchpadStreamService);
});
