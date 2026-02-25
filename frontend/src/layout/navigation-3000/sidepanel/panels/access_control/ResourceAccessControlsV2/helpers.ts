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

export function getMinLevelDisabledReason(
    inheritedLevel: AccessControlLevel | null,
    inheritedReason: InheritedReason,
    minimum: AccessControlLevel | null,
    resourceLabel: string
): string | undefined {
    if (inheritedReason === 'organization_admin') {
        return 'User is an organization admin'
    }
    if (inheritedLevel) {
        switch (inheritedReason) {
            case 'project_default':
                return `Project default is ${toSentenceCase(inheritedLevel)}`
            case 'role_override':
                return `User has a role with ${toSentenceCase(inheritedLevel)} access`
        }
    }
    if (minimum) {
        return `Minimum level for ${resourceLabel} is ${toSentenceCase(minimum)}`
    }
    return undefined
}

export function getLevelOptionsForResource(
    availableLevels: AccessControlLevel[],
    options?: {
        minimum?: AccessControlLevel | null
        maximum?: AccessControlLevel | null
        disabledReason?: string
    }
): { value: AccessControlLevel; label: string; disabledReason?: string }[] {
    const minimum = options?.minimum
    const maximum = options?.maximum
    const customDisabledReason = options?.disabledReason

    const minIndex = minimum ? availableLevels.indexOf(minimum) : -1
    const maxIndex = maximum ? availableLevels.indexOf(maximum) : availableLevels.length

    return availableLevels.map((level) => {
        const currentIndex = availableLevels.indexOf(level)
        const isDisabled = (minIndex >= 0 && currentIndex < minIndex) || (maxIndex >= 0 && currentIndex > maxIndex)

        return {
            value: level,
            label: level === AccessControlLevel.None ? 'None' : toSentenceCase(level),
            disabledReason: isDisabled ? (customDisabledReason ?? 'Not available for this feature') : undefined,
        }
    })
}
