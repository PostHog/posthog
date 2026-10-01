import {
    taskChannelsList,
    taskChannelsProvisionDefaultsCreate,
    taskChannelsRetrieve,
    tasksCreate,
    tasksRetrieve,
    tasksRunCreate,
} from 'products/tasks/frontend/generated/api'
import type { ChannelDTOApi, TaskDetailDTOApi } from 'products/tasks/frontend/generated/api.schemas'

export type CanvasSpace = Pick<ChannelDTOApi, 'id' | 'name' | 'system_role'>

export type CanvasGenerationTask = Pick<TaskDetailDTOApi, 'id' | 'title'> & {
    latest_run: Pick<NonNullable<TaskDetailDTOApi['latest_run']>, 'status'> | null
}

function toCanvasTask(task: Pick<TaskDetailDTOApi, 'id' | 'title' | 'latest_run'>): CanvasGenerationTask {
    return { id: task.id, title: task.title, latest_run: task.latest_run ?? null }
}

// pinned: task run statuses from the tasks API
const TERMINAL_RUN_STATUSES = new Set(['completed', 'failed', 'cancelled'])

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
