import { toSentenceCase } from 'lib/utils'

import { APIScopeObject, AccessControlLevel } from '~/types'

import { AccessControlSettingsEntry, InheritedReason, ScopeType } from './types'

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

export function getLevelOptionsForResource(
    availableLevels: AccessControlLevel[],
    options?: {
        minimum?: AccessControlLevel
        maximum?: AccessControlLevel
        disabledReason?: string
    }
): { value: AccessControlLevel; label: string; disabledReason?: string }[] {
    const minimum = options?.minimum
    const maximum = options?.maximum
    const customDisabledReason = options?.disabledReason

    return availableLevels.map((level) => {
        const minIndex = minimum ? availableLevels.indexOf(minimum) : -1
        const maxIndex = maximum ? availableLevels.indexOf(maximum) : availableLevels.length
        const currentIndex = availableLevels.indexOf(level)
        const isDisabled = (minIndex >= 0 && currentIndex < minIndex) || (maxIndex >= 0 && currentIndex > maxIndex)

        return {
            value: level,
            label: level === AccessControlLevel.None ? 'None' : toSentenceCase(level),
            disabledReason: isDisabled ? (customDisabledReason ?? 'Not available for this feature') : undefined,
        }
    })
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
    level: AccessControlLevel | null | undefined,
    reason: InheritedReason,
    resourceLabel?: string
): string | undefined {
    if (reason === 'organization_admin') {
        return 'User is an organization admin'
    }
    if (level && level !== 'none') {
        switch (reason) {
            case 'project_default':
                return `Project default is ${toSentenceCase(level)}`
            case 'role_override':
                return `User has a role with ${toSentenceCase(level)} access`
        }
    }
    if (level && level !== 'none' && resourceLabel) {
        return `Minimum level for ${resourceLabel} is ${toSentenceCase(level)}`
    }
    return undefined
}

export function getProjectDisabledReason(
    entry: AccessControlSettingsEntry,
    canEdit: boolean,
    loading: boolean
): string | undefined {
    if (loading) {
        return 'Loading...'
    }
    if (!canEdit) {
        return 'Cannot edit'
    }
    if (entry.project.inherited_access_level_reason === 'organization_admin') {
        return 'User is an organization admin'
    }
    return undefined
}

export function getFeaturesDisabledReason(
    entry: AccessControlSettingsEntry,
    canEdit: boolean,
    loading: boolean
): string | undefined {
    if (loading) {
        return 'Loading...'
    }
    if (!canEdit) {
        return 'Cannot edit'
    }
    if (entry.project.inherited_access_level_reason === 'organization_admin') {
        return 'User is an organization admin and has access to all features'
    }
    return undefined
}

export function getGroupedAccessControlRuleModalTitle(scopeType: ScopeType): string {
    switch (scopeType) {
        case 'default':
            return 'Update default access'
        case 'role':
            return 'Update role access'
        case 'member':
            return 'Update member access'
    }
}
