import type { ActiveCreation } from 'products/posthog_ai/frontend/api/logics'

/** A task the PostHog AI panel can show. The panel streams one run, so it needs the run, not only the task. */
export interface TodayPanelChatTask {
    taskId: string
    runId: string
}

/** The run open on the task page, else the latest one. A task that has never run can't move into the panel. */
export function panelChatTaskFor(
    task: { id: string; latest_run?: { id: string } | null },
    run: { id: string } | null
): TodayPanelChatTask | null {
    const runId = run?.id ?? task.latest_run?.id
    return runId ? { taskId: task.id, runId } : null
}

export function runnerCreationFor({ taskId, runId }: TodayPanelChatTask): ActiveCreation {
    return { streamKey: runId, taskId, runId }
}
