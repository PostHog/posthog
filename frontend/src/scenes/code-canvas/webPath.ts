import { urls } from 'scenes/urls'

/**
 * The web app path for an item a share link points at. Share links carry `?project=<id>` for the
 * project that owns the item, because the visitor's current project can be a different one. Older
 * links have no `project`, so they fall back to the current project.
 */
export function webPath(project: unknown, path: string): string {
    const projectId = typeof project === 'number' || typeof project === 'string' ? String(project) : ''
    return /^\d+$/.test(projectId) ? urls.project(projectId, path) : path
}
