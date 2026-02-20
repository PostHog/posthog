import { toSentenceCase } from 'lib/utils'

import { APIScopeObject, AccessControlLevel } from '~/types'

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
