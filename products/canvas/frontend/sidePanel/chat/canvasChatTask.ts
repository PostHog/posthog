import { CanvasGenerationTask, isStartingRunStatus, isTerminalRunStatus } from '../../canvasTasksApi'

// The run whose chat the side panel shows: the current person's own run on this canvas.
// Another person's run never shows, even while it is in flight, so on a shared canvas
// every editor keeps their own conversation. Mirrors PostHog Desktop's canvasChatTask.ts.
export function canvasChatTaskId(args: {
    /** The run this person just started here, before the canvas record caught up. */
    startedTaskId: string | null
    /** The canvas's generation task and its creator (undefined while the task loads). */
    generationTaskId: string | null
    generationTaskCreatorUuid: string | null | undefined
    /** Published versions, newest first. */
    versions: readonly { taskId: string | null; createdByUuid: string | null }[]
    currentUserUuid: string | null | undefined
}): string | null {
    if (args.startedTaskId) {
        return args.startedTaskId
    }
    if (!args.currentUserUuid) {
        return null
    }
    if (args.generationTaskId && args.generationTaskCreatorUuid === args.currentUserUuid) {
        return args.generationTaskId
    }
    const ownVersion = args.versions.find(
        (version) => !!version.taskId && version.createdByUuid === args.currentUserUuid
    )
    return ownVersion?.taskId ?? null
}

/** The task comments belong to: the canvas's generation task, else the newest version an agent published. */
export function canvasCommentTaskId(
    generationTaskId: string | null | undefined,
    versions: readonly { taskId: string | null }[]
): string | null {
    return generationTaskId ?? versions.find((version) => version.taskId)?.taskId ?? null
}

/**
 * What the Chat tab shows. "starting" is a run that exists or is being created but whose agent
 * has not begun, "running" is an agent at work, "awaiting" is an open run whose agent finished
 * its turn, and "start-failed" is a run that never started.
 */
export type CanvasChatState =
    | 'loading'
    | 'idle'
    | 'starting'
    | 'running'
    | 'awaiting'
    | 'finished'
    | 'failed'
    | 'start-failed'

export function canvasChatState(input: {
    chatTaskId: string | null
    chatTask: CanvasGenerationTask | null
    starting: boolean
    startError: string | null
    /** Whether the agent is working a turn of the run, or null when its session stream cannot tell. */
    agentTurnActive?: boolean | null
}): CanvasChatState {
    if (input.starting) {
        return 'starting'
    }
    if (!input.chatTaskId) {
        return input.startError ? 'start-failed' : 'idle'
    }
    if (!input.chatTask) {
        return 'loading'
    }
    const run = input.chatTask.latest_run
    if (!run) {
        return input.startError ? 'start-failed' : 'starting'
    }
    if (isStartingRunStatus(run.status)) {
        return 'starting'
    }
    if (!isTerminalRunStatus(run.status)) {
        // A cloud run stays open after the agent's turn so a follow-up can reuse it.
        return input.agentTurnActive === false ? 'awaiting' : 'running'
    }
    return run.status === 'completed' ? 'finished' : 'failed'
}
