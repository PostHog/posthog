import { ContainerModule } from "inversify";
import { CanvasV2BoardsService } from "./canvasV2BoardsService";
import { CANVAS_V2_BOARDS_SERVICE } from "./identifiers";

// Canvas v2 board persistence. It needs only the project API client that
// canvasCoreModule binds, so it loads beside that module on the host side and
// the host-router canvas-v2 router resolves it by token.
export const canvasV2CoreModule = new ContainerModule(({ bind }) => {
  bind(CanvasV2BoardsService).toSelf().inSingletonScope();
  bind(CANVAS_V2_BOARDS_SERVICE).toService(CanvasV2BoardsService);
});
