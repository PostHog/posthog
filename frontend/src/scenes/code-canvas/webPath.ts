import { getProjectIdentifierInPath } from 'lib/utils/kea-router'
import { urls } from 'scenes/urls'

/**
 * The web app path for an item a share link points at. The link's `/project/<id>/` prefix names
 * the project that owns the item, because the visitor's current project can be a different one.
 * Links without a project fall back to the current project.
 */
export function webPath(linkPathname: string, path: string): string {
    const projectId = getProjectIdentifierInPath(linkPathname)
    return projectId && /^\d+$/.test(projectId) ? urls.project(projectId, path) : path
}
