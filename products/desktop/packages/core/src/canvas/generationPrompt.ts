import { escapeXmlAttr } from "@posthog/shared";
import { FREEFORM_TEMPLATE_ID } from "./freeformSchemas";

// A generation task scoped to one placement on a grid canvas: the agent fills
// the drawn box by placing a store component or building a new one, following
// the composing-grid-canvases skill rather than the freeform one.
export function buildPlacementGenerationPrompt(input: {
  dashboardId: string;
  name: string;
  channelName: string;
  instruction: string;
  placementId: string;
  boxWidth: number;
  boxHeight: number;
}): string {
  return `${input.instruction}

<canvas_generation_instructions>
Invoke the \`composing-grid-canvases\` skill and follow it completely.

You are filling ONE placement on a grid canvas. Resolve it with the skill's
ladder: search the component store first, fork when close, build a new
component only when nothing fits. When the placement is ready, patch it to
status "live" with the component id and config, keeping its prompt intact.
On failure, patch it to status "failed" instead of leaving it generating.

Target:
- grid canvas id: "${escapeXmlAttr(input.dashboardId)}"
- grid canvas name: "${escapeXmlAttr(input.name)}"
- channel: "${escapeXmlAttr(input.channelName)}"
- placement id: "${escapeXmlAttr(input.placementId)}"
- drawn box: ${input.boxWidth}x${input.boxHeight} grid units (a small box wants a glanceable tile; a large one a full app surface)
</canvas_generation_instructions>`;
}

// A task scoped to a whole grid canvas: the agent edits the layout itself and
// the placed components, following the composing-grid-canvases skill.
export function buildGridCanvasGenerationPrompt(input: {
  dashboardId: string;
  name: string;
  channelName: string;
  instruction: string;
}): string {
  return `${input.instruction}

<canvas_generation_instructions>
Invoke the \`composing-grid-canvases\` skill and follow it completely.

You are working on the WHOLE grid canvas: add, fill, move, resize, or remove
placements as the instruction requires, and edit the placed component
canvases themselves when a widget needs fixing. One instruction often calls
for SEVERAL widgets (e.g. "a canvas summarizing work in progress" wants a
tile per concern): plan the full set first, resolve each with the skill's
ladder (place from the store, fork, or build new), and lay them all out
without overlap. Use the guarded patch loop, and never leave a placement in
the generating state when you finish.

Users leave feedback as comments on this canvas, attached to this task. List
them with the task comment tools (e.g. \`tasks-comments-list\`) before and
after making changes, and address the open ones.

Target:
- grid canvas id: "${escapeXmlAttr(input.dashboardId)}"
- grid canvas name: "${escapeXmlAttr(input.name)}"
- channel: "${escapeXmlAttr(input.channelName)}"
</canvas_generation_instructions>`;
}

export function buildCanvasGenerationPrompt(input: {
  dashboardId: string;
  name: string;
  channelName: string;
  templateId?: string;
  instruction: string;
}): string {
  // Only the legacy template ids name a layout the canvas skills define a shape
  // for. Every canvas created today is freeform, so passing that through would
  // put a meaningless "requested pattern" on every generation task.
  const template =
    input.templateId && input.templateId !== FREEFORM_TEMPLATE_ID
      ? `\n- requested pattern: "${escapeXmlAttr(input.templateId)}"`
      : "";

  return `${input.instruction}

<canvas_generation_instructions>
Invoke the \`building-canvases\` skill and follow it completely.

Target:
- canvas id: "${escapeXmlAttr(input.dashboardId)}"
- canvas name: "${escapeXmlAttr(input.name)}"
- channel: "${escapeXmlAttr(input.channelName)}"${template}
</canvas_generation_instructions>`;
}
