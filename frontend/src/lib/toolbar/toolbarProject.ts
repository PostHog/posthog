// The extension's service worker imports this module, so it must not import anything that reads `window`.

/** The project a toolbar OAuth token is scoped to, as named by the OAuth callback. */
export interface ToolbarProject {
    teamId: number
    projectId: number
}

/**
 * Which id a route takes. Routes registered with a `project_id` parent take the project id, routes registered with a
 * `team_id` parent take the team id, and `/api/environments/` routes always take the team id.
 */
export type ToolbarRouteScope = 'project' | 'team' | 'environment'

function asPositiveInteger(value: unknown): number | null {
    const parsed = typeof value === 'string' && /^\d+$/.test(value) ? Number(value) : value
    return typeof parsed === 'number' && Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null
}

export function asToolbarProject(teamId: unknown, projectId: unknown): ToolbarProject | null {
    const team = asPositiveInteger(teamId)
    const project = asPositiveInteger(projectId)
    return team && project ? { teamId: team, projectId: project } : null
}

export function toolbarScopedPath(project: ToolbarProject, scope: ToolbarRouteScope, path: string): string {
    if (scope === 'environment') {
        return `/api/environments/${project.teamId}/${path}`
    }
    return `/api/projects/${scope === 'project' ? project.projectId : project.teamId}/${path}`
}
