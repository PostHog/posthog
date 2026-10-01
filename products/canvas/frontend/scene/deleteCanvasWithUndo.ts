import posthog from 'posthog-js'

import { toast } from '@posthog/quill'

import { CANVAS_EVENTS, CanvasSurface } from '../canvasAnalytics'
import { canvasesDestroy } from '../generated/api'

// Nothing reaches the server until this runs out, so it is also the undo window.
export const CANVAS_DELETE_UNDO_MS = 8000

// Module level on purpose: the window outlives the scene that started it, because
// deleting from the canvas itself navigates away at once.
const pendingTimers = new Map<string, ReturnType<typeof setTimeout>>()

interface DeleteCanvasWithUndoOptions {
    projectId: string
    canvasId: string
    spaceId: string
    name: string
    surface: CanvasSurface
    /** Runs when the viewer undoes the delete, or when the delete fails. */
    onRestore: () => void
}

/** Deletes a canvas after an undo window. Undo cancels the timer, so nothing is ever recreated. */
export function deleteCanvasWithUndo({
    projectId,
    canvasId,
    spaceId,
    name,
    surface,
    onRestore,
}: DeleteCanvasWithUndoOptions): void {
    const properties = { surface, channel_id: spaceId, dashboard_id: canvasId }
    const existing = pendingTimers.get(canvasId)
    if (existing) {
        clearTimeout(existing)
    }

    const commit = async (): Promise<void> => {
        pendingTimers.delete(canvasId)
        try {
            await canvasesDestroy(projectId, canvasId)
            posthog.capture(CANVAS_EVENTS.dashboardAction, { action_type: 'delete', success: true, ...properties })
        } catch (error) {
            posthog.capture(CANVAS_EVENTS.dashboardAction, { action_type: 'delete', success: false, ...properties })
            toast.error({
                title: `Couldn't delete ${name}. ${error instanceof Error ? error.message : 'Try again in a moment.'}`,
            })
            onRestore()
        }
    }

    pendingTimers.set(
        canvasId,
        setTimeout(() => void commit(), CANVAS_DELETE_UNDO_MS)
    )

    toast.success({
        title: `Deleted ${name}`,
        timeout: CANVAS_DELETE_UNDO_MS,
        action: {
            label: 'Undo',
            onClick: () => {
                const timer = pendingTimers.get(canvasId)
                // No timer means the delete is already in flight or done.
                if (!timer) {
                    return
                }
                clearTimeout(timer)
                pendingTimers.delete(canvasId)
                posthog.capture(CANVAS_EVENTS.dashboardAction, { action_type: 'delete_undo', ...properties })
                onRestore()
            },
        },
    })
}

export function isCanvasDeletePending(canvasId: string): boolean {
    return pendingTimers.has(canvasId)
}
