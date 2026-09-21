import { injectable } from "inversify";
import { BUILT_IN_TEMPLATES } from "./canvasTemplates";
import type { ICanvasTemplatesService } from "./services";
import type { CanvasTemplateSummary } from "./templateSchemas";

@injectable()
export class CanvasTemplatesService implements ICanvasTemplatesService {
  list(): CanvasTemplateSummary[] {
    return BUILT_IN_TEMPLATES;
  }
}
