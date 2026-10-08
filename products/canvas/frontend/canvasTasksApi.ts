import {
    taskChannelsList,
    taskChannelsProvisionDefaultsCreate,
    taskChannelsRetrieve,
    tasksCreate,
    tasksRetrieve,
    tasksRunCreate,
    tasksRunsCommandCreate,
} from 'products/tasks/frontend/generated/api'
import type { ChannelDTOApi, TaskDetailDTOApi } from 'products/tasks/frontend/generated/api.schemas'

export type CanvasSpace = Pick<ChannelDTOApi, 'id' | 'name' | 'system_role'>
export type CanvasTaskRun = Pick<NonNullable<TaskDetailDTOApi['latest_run']>, 'id' | 'status'> &
    Partial<Pick<NonNullable<TaskDetailDTOApi['latest_run']>, 'error_message'>>
export type CanvasGenerationTask = Pick<TaskDetailDTOApi, 'id' | 'title'> & {
    latest_run: CanvasTaskRun | null
    created_by?: Pick<NonNullable<TaskDetailDTOApi['created_by']>, 'uuid'> | null
}

function toCanvasTask(
    task: Pick<TaskDetailDTOApi, 'id' | 'title' | 'latest_run' | 'created_by'>
): CanvasGenerationTask {
    return { id: task.id, title: task.title, latest_run: task.latest_run ?? null, created_by: task.created_by }
}

// pinned: task run statuses from the tasks API
const TERMINAL_RUN_STATUSES = new Set(['completed', 'failed', 'cancelled'])
const STARTING_RUN_STATUSES = new Set(['not_started', 'queued'])

/** Whether a run exists but its agent has not begun work yet. */
export function isStartingRunStatus(status: string | null | undefined): boolean {
    return !!status && STARTING_RUN_STATUSES.has(status)
}

export function isTerminalRunStatus(status: string | null | undefined): boolean {
    return !!status && TERMINAL_RUN_STATUSES.has(status)
}

function toSpaces(response: unknown): CanvasSpace[] {
    const rows = Array.isArray(response) ? response : ((response as { results?: unknown[] })?.results ?? [])
    return (rows as Record<string, unknown>[]).map((row) => ({
        id: String(row.id),
        name: String(row.name ?? ''),
        system_role: row.system_role === 'personal' || row.system_role === 'general' ? row.system_role : null,
    }))
}

/** The spaces the user can see. Provisions the personal space when it does not exist yet. */
export async function loadCanvasSpaces(projectId: string): Promise<CanvasSpace[]> {
    const spaces = toSpaces(await taskChannelsList(projectId))
    if (spaces.some((space) => space.system_role === 'personal')) {
        return spaces
    }
    const provisioned = await taskChannelsProvisionDefaultsCreate(projectId)
    return toSpaces(provisioned.channels)
}

export async function loadCanvasSpace(projectId: string, spaceId: string): Promise<CanvasSpace> {
    const [space] = toSpaces([await taskChannelsRetrieve(projectId, spaceId)])
    return space
}

/** The label a person sees for a space. It matches the Spaces sidebar, which shows the personal space as "Me". */
export function canvasSpaceLabel(space: Pick<CanvasSpace, 'name' | 'system_role'>): string {
    return space.system_role === 'personal' ? 'Me' : space.name
}

/**
 * Starts the cloud task that builds a canvas. The run is unattended, so it bypasses
 * permission prompts the same way PostHog Desktop's canvas generation does. The model
 * is left to the server default. The server titles the task synchronously.
 */
export async function createCanvasGenerationTask(
    projectId: string,
    input: { description: string; namingSource: string; spaceId: string; startRun?: boolean }
): Promise<CanvasGenerationTask> {
    return toCanvasTask(
        await tasksCreate(projectId, {
            description: input.description,
            // The server titles the task from this, so the title reflects the request, not the injected instructions.
            naming_source: input.namingSource,
            origin_product: 'user_created',
            channel: input.spaceId,
            start_run: input.startRun ?? true,
            initial_permission_mode: 'bypassPermissions',
        })
    )
}

export async function loadCanvasGenerationTask(projectId: string, taskId: string): Promise<CanvasGenerationTask> {
    return toCanvasTask(await tasksRetrieve(projectId, taskId))
}

export async function startCanvasGenerationRun(projectId: string, taskId: string): Promise<CanvasGenerationTask> {
    return toCanvasTask(
        await tasksRunCreate(projectId, taskId, {
            mode: 'background',
            run_source: 'manual',
            initial_permission_mode: 'bypassPermissions',
        })
    )
}

/** Sends a follow-up message to a run that is still live. The agent reads it on its next turn. */
export async function sendCanvasRunMessage(
    projectId: string,
    taskId: string,
    runId: string,
    content: string
): Promise<void> {
    const response = await tasksRunsCommandCreate(projectId, taskId, runId, {
        jsonrpc: '2.0',
        method: 'user_message',
        params: { content },
    })
    const result = response.result
    if (!result || typeof result !== 'object' || !('queued' in result) || result.queued !== true) {
        throw new Error("The agent didn't confirm the message.")
    }
}

/**
 * Starts a new run of a task with a follow-up message. Chained from the last run, the new run
 * continues that conversation. The server answers with the task, the new run as `latest_run`.
 */
export async function resumeCanvasTask(
    projectId: string,
    taskId: string,
    input: { resumeFromRunId: string | null; message: string }
): Promise<CanvasGenerationTask> {
    return toCanvasTask(
        await tasksRunCreate(projectId, taskId, {
            ...(input.resumeFromRunId ? { resume_from_run_id: input.resumeFromRunId } : {}),
            pending_user_message: input.message,
        })
    )
}
