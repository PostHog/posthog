import type { z } from "zod";
import {
  type CanvasActionDefinition,
  type CanvasActionResult,
  canvasActionDefinitionSchema,
  type canvasActionInvokeInput,
} from "./dashboardSchemas";

export async function invokeCanvasAction(
  input: z.infer<typeof canvasActionInvokeInput>,
  listActions: () => Promise<CanvasActionDefinition[]>,
  confirm: (action: CanvasActionDefinition) => boolean,
  invoke: (
    input: z.infer<typeof canvasActionInvokeInput>,
  ) => Promise<CanvasActionResult>,
): Promise<CanvasActionResult> {
  const actions = canvasActionDefinitionSchema
    .array()
    .parse(await listActions());
  const action = actions.find((entry) => entry.verb === input.verb);
  if (!action) throw new Error("Unknown canvas action");
  if (action.destructive && !confirm(action)) {
    throw new Error("Canvas action canceled");
  }
  return invoke(input);
}
