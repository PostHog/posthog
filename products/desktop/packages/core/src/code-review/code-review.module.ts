import { ContainerModule } from "inversify";
import { REVERT_HUNK_SERVICE } from "./identifiers";
import { RevertHunkService } from "./revertHunkService";

export const codeReviewModule = new ContainerModule(({ bind }) => {
  bind(REVERT_HUNK_SERVICE).to(RevertHunkService).inSingletonScope();
});
