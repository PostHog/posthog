import type { z } from "zod";
import {
  type CanvasActionDefinition,
  type CanvasActionResult,
  type CanvasToolDefinition,
  type CanvasToolResult,
  canvasActionDefinitionSchema,
  type canvasActionInvokeInput,
  canvasToolDefinitionSchema,
  type canvasToolInvokeInput,
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

// ph.tools.read runs without a click, so it takes read-only tools only.
// ph.tools.call comes from a click, and the viewer confirms every tool that
// is not read-only, with the exact arguments the canvas passes.
export async function invokeCanvasTool(
  input: z.infer<typeof canvasToolInvokeInput>,
  fromGesture: boolean,
  listTools: () => Promise<CanvasToolDefinition[]>,
  confirm: (
    tool: CanvasToolDefinition,
    args: Record<string, unknown>,
  ) => boolean,
  invoke: (
    input: z.infer<typeof canvasToolInvokeInput>,
  ) => Promise<CanvasToolResult>,
): Promise<CanvasToolResult> {
  const tools = canvasToolDefinitionSchema.array().parse(await listTools());
  const tool = tools.find((entry) => entry.name === input.tool);
  if (!tool) throw new Error(`Canvases cannot run the tool "${input.tool}"`);
  if (!fromGesture && !tool.read_only) {
    throw new Error(
      `"${input.tool}" changes data. Run it with ph.tools.call from a click.`,
    );
  }
  if (!tool.read_only && !confirm(tool, input.arguments)) {
    throw new Error("Canvas tool call canceled");
  }
  return invoke(input);
}
