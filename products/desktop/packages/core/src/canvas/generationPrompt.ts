import { escapeXmlAttr } from "@posthog/shared";
import { FREEFORM_TEMPLATE_ID } from "./freeformSchemas";

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
