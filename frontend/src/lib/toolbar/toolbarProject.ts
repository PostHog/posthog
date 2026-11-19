// The extension's service worker imports this module, so it must not import anything that reads `window`.

/** The project a toolbar OAuth token is scoped to, as named by the OAuth callback. */
export interface ToolbarProject {
    teamId: number
    projectId: number
}

/** Which id a route takes: routes registered with a `project_id` parent take the project id, the rest the team id. */
export type ToolbarRouteScope = 'project' | 'team'

function asPositiveInteger(value: unknown): number | null {
    const parsed = typeof value === 'string' && /^\d+$/.test(value) ? Number(value) : value
    return typeof parsed === 'number' && Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null
}

export function asToolbarProject(teamId: unknown, projectId: unknown): ToolbarProject | null {
    const team = asPositiveInteger(teamId)
    const project = asPositiveInteger(projectId)
    return team && project ? { teamId: team, projectId: project } : null
}

/** An app path inside the session's project. Without the prefix the app opens the user's current project instead. */
export function toolbarAppPath(project: ToolbarProject | null, path: string): string {
    return project ? `/project/${project.teamId}${path}` : path
}

export function toolbarScopedPath(project: ToolbarProject, scope: ToolbarRouteScope, path: string): string {
    return `/api/projects/${scope === 'project' ? project.projectId : project.teamId}/${path}`
}
