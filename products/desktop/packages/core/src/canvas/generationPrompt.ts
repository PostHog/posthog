import { escapeXmlAttr } from "@posthog/shared";

export function buildCanvasGenerationPrompt(input: {
  dashboardId: string;
  name: string;
  channelName: string;
  templateId?: string;
  instruction: string;
}): string {
  const template = input.templateId
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
