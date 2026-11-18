import { ProjectBasicType } from '~/types'

/**
 * Mirrors the API's uniqueness rule for project names, which trims and compares case-insensitively
 * (see `ProjectBackwardCompatSerializer.validate_name`). When renaming, pass the project's own id and
 * stored name so it does not collide with itself.
 *
 * This can only be an early warning. The organization payload carries the projects the user can see
 * and no deletion state, so the API still has the final say.
 */
export function isProjectNameTaken(
    candidate: string,
    projects: ProjectBasicType[] | undefined,
    { excludeProjectId, currentName }: { excludeProjectId?: number; currentName?: string } = {}
): boolean {
    const trimmed = candidate.trim()
    // Projects created before the rule existed can still share a name, and the API keeps accepting a
    // save that leaves such a name alone. Flagging it would accuse the user on page load.
    if (currentName !== undefined && trimmed === currentName) {
        return false
    }
    const normalized = trimmed.toLowerCase()
    return !!projects?.some(
        (project) => project.id !== excludeProjectId && project.name.trim().toLowerCase() === normalized
    )
}
