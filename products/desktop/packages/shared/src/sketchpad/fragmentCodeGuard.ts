import {
  CANVAS_BASE_ALLOWED_IMPORTS,
  checkCanvasCode,
} from "../canvasCodeGuard";

export const SKETCHPAD_ALLOWED_IMPORTS = CANVAS_BASE_ALLOWED_IMPORTS;

export function checkFragmentCode(code: string) {
  return checkCanvasCode(code, SKETCHPAD_ALLOWED_IMPORTS);
}
