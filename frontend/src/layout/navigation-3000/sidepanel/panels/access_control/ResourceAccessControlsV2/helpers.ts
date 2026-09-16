import { toSentenceCase } from 'lib/utils/strings'

import { APIScopeObject, AccessControlLevel, EffectiveAccessControlEntry } from '~/types'

import type { InheritedAccess } from '../accessControlLogic'
import { AccessControlMemberEntry, AccessControlRoleEntry, AccessControlSettingsEntry, InheritedReason } from './types'

export function describeAccessControlLevel(
    level: AccessControlLevel | null | undefined,
    resourceKey: APIScopeObject
): string {
    if (level === null || level === undefined || level === AccessControlLevel.None) {
        return 'No access.'
    }

    if (resourceKey === 'project') {
        if (level === AccessControlLevel.Member) {
            return 'Project member access. Can use the project, but cannot manage project settings.'
        }
        if (level === AccessControlLevel.Admin) {
            return 'Project admin access. Full access, including managing project settings.'
        }
        if (level === AccessControlLevel.Viewer) {
            return 'Read-only access to the project.'
        }
    }

    if (level === AccessControlLevel.Viewer) {
        return 'View-only access. Cannot make changes.'
    }
    if (level === AccessControlLevel.Editor) {
        return 'Edit access. Can create and modify items.'
    }
    if (level === AccessControlLevel.Manager) {
        return 'Manage access. Can configure and manage items.'
    }

    return `${toSentenceCase(level)} access.`
}

export function humanizeAccessControlLevel(level: AccessControlLevel | null | undefined): string {
    if (level === null || level === undefined || level === AccessControlLevel.None) {
        return 'No access'
    }
    return toSentenceCase(level)
}

export function isRoleEntry(entry: AccessControlSettingsEntry): entry is AccessControlRoleEntry {
    return 'role_id' in entry
}

export function isMemberEntry(entry: AccessControlSettingsEntry): entry is AccessControlMemberEntry {
    return 'organization_membership_id' in entry
}

export interface AccessSummaryTag {
    resource: string
    level: string
}

/** Builds the "Access" column tags for a role/member entry, excluding resources whose
 * product isn't rolled out to the current user even if a stale access level exists for it.
 *
 * `filteredResources` are the tools selected in the Tool filter. If the set is not empty, the row
 * shows tags for those tools only, and no project tag. Each tag then answers the question the
 * filter asked. */
export function getAccessSummaryTags(
    entry: AccessControlSettingsEntry,
    visibleResources: Set<APIScopeObject>,
    filteredResources?: Set<APIScopeObject>
): AccessSummaryTag[] {
    const tags: AccessSummaryTag[] = []

    if (!filteredResources?.size && entry.project.effective_access_level !== null) {
        tags.push({ resource: 'project', level: entry.project.effective_access_level })
    }

    for (const [resource, resourceEntry] of Object.entries(entry.resources)) {
        if (resourceEntry.effective_access_level === null || !visibleResources.has(resource as APIScopeObject)) {
            continue
        }
        if (filteredResources?.size && !filteredResources.has(resource as APIScopeObject)) {
            continue
        }
        tags.push({ resource, level: resourceEntry.effective_access_level })
    }

    return tags
}

export function getEntryId(entry: AccessControlSettingsEntry): string {
    if (isRoleEntry(entry)) {
        return entry.role_id
    }
    if (isMemberEntry(entry)) {
        return entry.organization_membership_id
    }
    throw new Error('Unknown entry type')
}

/**
 * The settings UI's phrasing of why a subject falls back to a level, from the entry's inherited
 * provenance: the org-admin bypass, a role's rule, or a default (a stored default rule or the
 * built-in one — both are "the default" to a person editing overrides).
 */
export function inheritedReasonOf(inherited: EffectiveAccessControlEntry['inherited_access']): InheritedReason {
    if (!inherited) {
        return null
    }
    if (inherited.source === 'org_admin') {
        return 'organization_admin'
    }
    if (inherited.source_subject === 'role') {
        return 'role_override'
    }
    return 'project_default'
}

export function getInheritedReasonTooltip(reason: InheritedReason): string | undefined {
    switch (reason) {
        case 'project_default':
            return 'Based on project default permissions'
        case 'role_override':
            return 'Based on role permissions'
        default:
            return undefined
    }
}

export function getLevelOptionsForResource(
    availableLevels: AccessControlLevel[],
    options?: {
        minimum: AccessControlLevel | null
        maximum: AccessControlLevel | null
        inheritedLevel: AccessControlLevel | null
        inheritedReason: InheritedReason
        resourceLabel: string
    }
): { value: AccessControlLevel; label: string; disabledReason?: string }[] {
    const { minimum, maximum, inheritedLevel, inheritedReason, resourceLabel } = options ?? {}
    const effectiveMinimum = inheritedLevel ?? minimum

    const minIndex = effectiveMinimum ? availableLevels.indexOf(effectiveMinimum) : -1
    const maxIndex = maximum ? availableLevels.indexOf(maximum) : availableLevels.length

    return availableLevels.map((level) => {
        const currentIndex = availableLevels.indexOf(level)
        const isBelowMin = minIndex >= 0 && currentIndex < minIndex
        const isAboveMax = maxIndex >= 0 && currentIndex > maxIndex

        let disabledReason: string | undefined
        if (isBelowMin) {
            if (inheritedReason === 'organization_admin') {
                disabledReason = 'User is an organization admin'
            } else if (inheritedReason === 'project_default' && inheritedLevel) {
                disabledReason = `Project default is ${toSentenceCase(inheritedLevel)}`
            } else if (inheritedReason === 'role_override' && inheritedLevel) {
                disabledReason = `User has a role with ${toSentenceCase(inheritedLevel)} access`
            } else if (minimum) {
                disabledReason = `Minimum level for ${resourceLabel} is ${toSentenceCase(minimum)}`
            }
        } else if (isAboveMax && maximum) {
            disabledReason = `Maximum level for ${resourceLabel} is ${toSentenceCase(maximum)}`
        } else {
            disabledReason = undefined // not disabled
        }

        return {
            value: level,
            // Matches humanizeAccessControlLevel, so every V2 surface calls the level "No access"
            label: level === AccessControlLevel.None ? 'No access' : toSentenceCase(level),
            disabledReason,
        }
    })
}

function inheritedReason(reason: InheritedReason, fallbackTo: string): string {
    switch (reason) {
        case 'role_override':
            return 'Based on role permissions'
        case 'organization_admin':
            return 'Organization admins always have full access'
        default:
            return `Based on the default for ${fallbackTo}`
    }
}

/**
 * What applies to a resource when the subject has no rule of their own. The entry resolves it
 * server-side, down to the built-in default when no rule exists anywhere.
 */
export function inheritedFor(res: EffectiveAccessControlEntry | undefined, fallbackTo: string): InheritedAccess | null {
    const inherited = res?.inherited_access ?? null
    if (!inherited) {
        return null
    }
    return {
        label: humanizeAccessControlLevel(inherited.access_level),
        reason: inheritedReason(inheritedReasonOf(inherited), fallbackTo),
    }
}

export function subjectDisabledReason(
    entry: AccessControlSettingsEntry,
    canEdit: boolean,
    currentUserUuid?: string
): string | undefined {
    if (!canEdit) {
        return 'You cannot edit this'
    }
    // Blocking self-edits keeps an admin from accidentally locking themselves out, and anyone
    // from quietly raising their own access
    if (isMemberEntry(entry) && currentUserUuid && entry.user.uuid === currentUserUuid) {
        return 'You cannot change your own access'
    }
    if (inheritedReasonOf(entry.project.inherited_access) === 'organization_admin') {
        return 'Organization admins always have full access'
    }
    return undefined
}
