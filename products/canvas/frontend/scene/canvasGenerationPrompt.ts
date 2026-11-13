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
