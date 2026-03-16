import { toSentenceCase } from 'lib/utils'

import { APIScopeObject, AccessControlLevel } from '~/types'

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

export function getEntryId(entry: AccessControlSettingsEntry): string {
    if (isRoleEntry(entry)) {
        return entry.role_id
    }
    if (isMemberEntry(entry)) {
        return entry.organization_membership_id
    }
    throw new Error('Unknown entry type')
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
            label: level === AccessControlLevel.None ? 'None' : toSentenceCase(level),
            disabledReason,
        }
    })
}
