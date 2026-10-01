import api from 'lib/api'

// Spaces and tasks belong to the tasks product. Its generated client lives in
// products/tasks/frontend/generated, which another product must not import, and the
// core generated client does not cover these endpoints. So these calls go through
// lib/api, and the types below project only the fields a canvas reads.

export interface CanvasSpace {
    id: string
    name: string
    system_role: 'personal' | 'general' | null
}

export interface CanvasGenerationTask {
    id: string
    title: string
    latest_run: { status: string } | null
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
    const spaces = toSpaces(await api.get(`api/projects/${projectId}/task_channels/`))
    if (spaces.some((space) => space.system_role === 'personal')) {
        return spaces
    }
    const provisioned = await api.create<{ channels: unknown[] }>(
        `api/projects/${projectId}/task_channels/provision_defaults/`
    )
    return toSpaces(provisioned.channels)
}

export async function loadCanvasSpace(projectId: string, spaceId: string): Promise<CanvasSpace> {
    const [space] = toSpaces([await api.get(`api/projects/${projectId}/task_channels/${spaceId}/`)])
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
    return api.create<CanvasGenerationTask>(`api/projects/${projectId}/tasks/`, {
        description: input.description,
        // The server titles the task from this, so the title reflects the request, not the injected instructions.
        naming_source: input.namingSource,
        origin_product: 'user_created',
        channel: input.spaceId,
        start_run: input.startRun ?? true,
        initial_permission_mode: 'bypassPermissions',
    })
}

export async function loadCanvasGenerationTask(projectId: string, taskId: string): Promise<CanvasGenerationTask> {
    return api.get<CanvasGenerationTask>(`api/projects/${projectId}/tasks/${taskId}/`)
}

export async function startCanvasGenerationRun(projectId: string, taskId: string): Promise<CanvasGenerationTask> {
    return api.create<CanvasGenerationTask>(`api/projects/${projectId}/tasks/${taskId}/run/`, {
        mode: 'background',
        run_source: 'agent',
        initial_permission_mode: 'bypassPermissions',
    })
}
