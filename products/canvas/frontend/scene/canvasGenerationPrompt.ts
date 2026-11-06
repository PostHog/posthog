import { FREEFORM_TEMPLATE_ID } from '../canvasTemplates'

// pinned: tag the task harness recognizes as injected canvas instructions, shared with PostHog Desktop
const CANVAS_INSTRUCTIONS_TAG = 'canvas_generation_instructions'

function escapeXmlAttr(value: string): string {
    return value
        .replace(/&/g, '&amp;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&apos;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
}

/** The prompt that routes a cloud task to the building-canvases skill for one canvas. */
/** The line every generation prompt names its canvas with, so a search can find that canvas's runs and no others. */
export function canvasPromptTarget(canvasId: string): string {
    return `canvas id: "${escapeXmlAttr(canvasId)}"`
}

/** Whether a task's prompt is a generation prompt for this canvas: its instructions block names the canvas as the target. */
export function isCanvasGenerationPrompt(description: string | null | undefined, canvasId: string): boolean {
    const start = description?.indexOf(`<${CANVAS_INSTRUCTIONS_TAG}>`) ?? -1
    const end = description?.indexOf(`</${CANVAS_INSTRUCTIONS_TAG}>`, start) ?? -1
    return start >= 0 && end > start && description!.slice(start, end).includes(`- ${canvasPromptTarget(canvasId)}`)
}

export function buildCanvasGenerationPrompt(input: {
    canvasId: string
    name: string
    spaceName: string
    templateId?: string
    instruction: string
}): string {
    // Every canvas created today is freeform, which names no layout for the skill to follow.
    const template =
        input.templateId && input.templateId !== FREEFORM_TEMPLATE_ID
            ? `\n- requested pattern: "${escapeXmlAttr(input.templateId)}"`
            : ''

    return `${input.instruction}

<${CANVAS_INSTRUCTIONS_TAG}>
Invoke the \`building-canvases\` skill and follow it completely.
If the canvas source has \`src/blocks/runtime.tsx\`, read the skill's \`references/blocks.md\` before you edit, and keep the canvas's blocks.
Expose the values a person may want to change as params with \`editable()\`, as the skill's "Params" section describes.

Target:
- ${canvasPromptTarget(input.canvasId)}
- canvas name: "${escapeXmlAttr(input.name)}"
- channel: "${escapeXmlAttr(input.spaceName)}"${template}
</${CANVAS_INSTRUCTIONS_TAG}>`
}
