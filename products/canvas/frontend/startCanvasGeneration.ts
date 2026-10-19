import posthog from 'posthog-js'

import { CANVAS_EVENTS, CanvasSurface } from './canvasAnalytics'
import { CanvasGenerationTask, createCanvasGenerationTask, startCanvasGenerationRun } from './canvasTasksApi'
import { isPlaceholderCanvasName } from './canvasTemplates'
import { canvasesPartialUpdate } from './generated/api'
import type { CanvasApi } from './generated/api.schemas'
import { buildCanvasGenerationPrompt } from './scene/canvasGenerationPrompt'

export interface StartCanvasGenerationInput {
    projectId: string
    canvas: CanvasApi
    /** The space's name for the agent. Falls back to the space id when the space has not loaded. */
    spaceName: string | null
    instruction: string
    fromSuggestion: boolean
    surface: CanvasSurface
}

export interface StartedCanvasGeneration {
    canvas: CanvasApi
    task: CanvasGenerationTask
}

/**
 * Links the agent task to the canvas before starting its run.
 * A placeholder name takes the task's title. Throws when the task does not start.
 */
export async function startCanvasGeneration({
    projectId,
    canvas,
    spaceName,
    instruction,
    fromSuggestion,
    surface,
}: StartCanvasGenerationInput): Promise<StartedCanvasGeneration> {
    const trimmed = instruction.trim()
    posthog.capture(CANVAS_EVENTS.promptSent, {
        surface,
        dashboard_id: canvas.id,
        from_suggestion: fromSuggestion,
        prompt_length_chars: trimmed.length,
    })
    const task = await createCanvasGenerationTask(projectId, {
        description: buildCanvasGenerationPrompt({
            canvasId: canvas.id,
            name: canvas.name,
            spaceName: spaceName ?? canvas.channel,
            templateId: canvas.template_id,
            instruction: trimmed,
        }),
        namingSource: trimmed,
        spaceId: canvas.channel,
        startRun: false,
    })
    const autoName = isPlaceholderCanvasName(canvas.name) && task.title?.trim()
    const updated = await canvasesPartialUpdate(projectId, canvas.id, {
        generation_task_id: task.id,
        ...(autoName ? { name: task.title.trim() } : {}),
    })
    return { canvas: updated, task: await startCanvasGenerationRun(projectId, task.id) }
}
