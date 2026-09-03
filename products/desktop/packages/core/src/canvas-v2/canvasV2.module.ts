import { ContainerModule } from "inversify";
import { CanvasV2BoardsService } from "./canvasV2BoardsService";
import { CanvasV2StreamService } from "./canvasV2StreamService";
import {
  CANVAS_V2_BOARDS_SERVICE,
  CANVAS_V2_STREAM_SERVICE,
} from "./identifiers";

// Canvas v2 board persistence. It needs only the project API client that
// canvasCoreModule binds, so it loads beside that module on the host side and
// the host-router canvas-v2 router resolves it by token.
export const canvasV2CoreModule = new ContainerModule(({ bind }) => {
  bind(CanvasV2BoardsService).toSelf().inSingletonScope();
  bind(CANVAS_V2_BOARDS_SERVICE).toService(CanvasV2BoardsService);
  bind(CanvasV2StreamService).toSelf().inSingletonScope();
  bind(CANVAS_V2_STREAM_SERVICE).toService(CanvasV2StreamService);
});
